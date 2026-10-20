"""Archive SQLite des mesures : mesures brutes sur 30 jours glissants,
agregats horaires, dernier record de chaque capteur et dernier offset
consomme de chaque partition. Ecrite par lots par le consommateur, lue au
demarrage par le dashboard. Methodes synchrones : a appeler via
asyncio.to_thread."""

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from contextlib import closing
from pathlib import Path

from app.data_management.data_processing.alert_rules import is_number
from app.data_management.records import HISTORY_MS, HOUR_MS, sensor_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurement (
    topic TEXT NOT NULL, partition INTEGER NOT NULL, offset INTEGER NOT NULL,
    sensor_id TEXT NOT NULL, ts_ms INTEGER NOT NULL, value REAL NOT NULL,
    PRIMARY KEY (topic, partition, offset)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS measurement_by_sensor
    ON measurement (topic, sensor_id, ts_ms);
CREATE TABLE IF NOT EXISTS hourly (
    topic TEXT NOT NULL, sensor_id TEXT NOT NULL, hour INTEGER NOT NULL,
    count INTEGER NOT NULL, sum REAL NOT NULL, min REAL NOT NULL,
    max REAL NOT NULL,
    PRIMARY KEY (topic, sensor_id, hour)
);
CREATE TABLE IF NOT EXISTS latest (
    topic TEXT NOT NULL, sensor_id TEXT NOT NULL, ts_ms INTEGER NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (topic, sensor_id)
);
CREATE TABLE IF NOT EXISTS cursor (
    topic TEXT NOT NULL, partition INTEGER NOT NULL,
    max_offset INTEGER NOT NULL,
    PRIMARY KEY (topic, partition)
);
"""

INSERT_MEASUREMENT = """
INSERT OR IGNORE INTO measurement
    (topic, partition, offset, sensor_id, ts_ms, value)
VALUES (?, ?, ?, ?, ?, ?)"""
UPSERT_HOURLY = """
INSERT INTO hourly (topic, sensor_id, hour, count, sum, min, max)
VALUES (?, ?, ?, 1, ?, ?, ?)
ON CONFLICT (topic, sensor_id, hour) DO UPDATE SET
    count = count + 1, sum = sum + excluded.sum,
    min = min(min, excluded.min), max = max(max, excluded.max)"""
UPSERT_LATEST = """
INSERT INTO latest (topic, sensor_id, ts_ms, record) VALUES (?, ?, ?, ?)
ON CONFLICT (topic, sensor_id) DO UPDATE SET
    ts_ms = excluded.ts_ms, record = excluded.record
WHERE excluded.ts_ms >= latest.ts_ms"""
UPSERT_CURSOR = """
INSERT INTO cursor (topic, partition, max_offset) VALUES (?, ?, ?)
ON CONFLICT (topic, partition) DO UPDATE SET
    max_offset = max(max_offset, excluded.max_offset)"""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class HistoryStore:
    def __init__(self, path: Path, retention_ms: int = HISTORY_MS,
                 clock: Callable[[], int] | None = None) -> None:
        self.path = Path(path)
        self._retention_ms = retention_ms
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._purged_ms = self._clock()  # premiere purge une heure apres le demarrage
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            # WAL (persistant) : le chargement ne bloque pas les lots
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # Une connexion par appel, dans le thread qui s'en sert. NORMAL : un
        # plantage du processus ne perd rien ; seule une panne machine peut
        # perdre les derniers lots, que Kafka relivre s'ils ne sont pas commites
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def insert(self, records: Iterable[dict]) -> int:
        """Nombre de mesures archivees. Un doublon (meme topic, partition,
        offset) ou un record sans mesure numerique datee ne compte pas, mais
        tout offset entier avance le curseur de sa partition."""
        rows, cursors = [], {}
        for record in records:
            topic, partition, offset = (record.get("topic"),
                                        record.get("partition"),
                                        record.get("offset"))
            if not isinstance(topic, str) or not _is_int(partition) \
                    or not _is_int(offset):
                continue
            cursors[(topic, partition)] = max(
                cursors.get((topic, partition), -1), offset)
            payload, ts_ms = record.get("value"), record.get("timestamp_ms")
            if isinstance(payload, dict) and is_number(payload.get("value")) \
                    and _is_int(ts_ms):
                rows.append((topic, partition, offset, sensor_id(record), ts_ms,
                             float(payload["value"]), record))
        inserted = 0
        with closing(self._connect()) as conn, conn:
            for topic, partition, offset, sensor, ts_ms, value, record in rows:
                # rowcount 0 : deja archive, ne pas le recompter
                if conn.execute(INSERT_MEASUREMENT, (topic, partition, offset,
                                                     sensor, ts_ms, value)
                                ).rowcount != 1:
                    continue
                inserted += 1
                conn.execute(UPSERT_HOURLY, (topic, sensor, ts_ms - ts_ms % HOUR_MS,
                                             value, value, value))
                conn.execute(UPSERT_LATEST, (topic, sensor, ts_ms,
                                             json.dumps(record, ensure_ascii=False)))
            conn.executemany(UPSERT_CURSOR,
                             [(t, p, o) for (t, p), o in cursors.items()])
            self._purge(conn)
        return inserted

    def _purge(self, conn: sqlite3.Connection) -> None:
        """Au plus une fois par heure, dans la transaction du lot."""
        now = self._clock()
        if now - self._purged_ms < HOUR_MS:
            return
        self._purged_ms = now  # avant le DELETE : un double passage est inoffensif
        cutoff = now - self._retention_ms
        # Par capteur : la suppression suit l'index, sans balayage complet
        for topic, sensor in conn.execute(
                "SELECT topic, sensor_id FROM latest").fetchall():
            conn.execute("DELETE FROM measurement WHERE topic = ? AND sensor_id = ?"
                         " AND ts_ms < ?", (topic, sensor, cutoff))
        conn.execute("DELETE FROM hourly WHERE hour < ?", (cutoff,))

    def positions(self, topic: str) -> dict[int, int]:
        """Dernier offset consomme par partition."""
        with closing(self._connect()) as conn:
            return dict(conn.execute(
                "SELECT partition, max_offset FROM cursor WHERE topic = ?",
                (topic,)).fetchall())

    def load(self, now_ms: int, raw_ms: int, history_ms: int) -> dict:
        """Etat du jumeau : par capteur, dernier record, points des `raw_ms`
        dernieres ms et cases horaires des `history_ms` dernieres ; `seen` =
        prefixe consomme de chaque partition."""
        sensors, seen = [], {}
        with closing(self._connect()) as conn:
            for topic, partition, max_offset in conn.execute(
                    "SELECT topic, partition, max_offset FROM cursor").fetchall():
                seen.setdefault(topic, {})[str(partition)] = [[0, max_offset]]
            for topic, sensor, record in conn.execute(
                    "SELECT topic, sensor_id, record FROM latest").fetchall():
                points = conn.execute(
                    "SELECT ts_ms, value FROM measurement WHERE topic = ?"
                    " AND sensor_id = ? AND ts_ms >= ? ORDER BY ts_ms",
                    (topic, sensor, now_ms - raw_ms)).fetchall()
                hours = conn.execute(
                    "SELECT hour, count, sum, min, max FROM hourly WHERE topic = ?"
                    " AND sensor_id = ? AND hour >= ?",
                    (topic, sensor, now_ms - history_ms)).fetchall()
                sensors.append({
                    "topic": topic, "id": sensor, "record": json.loads(record),
                    "points": [list(p) for p in points],
                    "hours": {str(h): [c, s, lo, hi] for h, c, s, lo, hi in hours},
                })
        return {"sensors": sensors, "seen": seen}
