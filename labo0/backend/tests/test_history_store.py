import asyncio
import sqlite3
from contextlib import closing

from app.data_management.data_storage.history_store import HistoryStore
from app.data_management.records import HISTORY_MS, HOUR_MS
from tests.conftest import make_measurement, make_record

CO2 = "gridd.obs.environmental.co2"
NOW = 10 * HISTORY_MS


def rows(store: HistoryStore, sql: str) -> list:
    with closing(sqlite3.connect(store.path)) as conn:
        return conn.execute(sql).fetchall()


class TestSchema:
    def test_created_with_parent_dirs_and_wal(self, tmp_path):
        store = HistoryStore(tmp_path / "a" / "b" / "history.sqlite")

        assert store.path.is_file()
        assert rows(store, "PRAGMA journal_mode") == [("wal",)]
        assert store.load(NOW, HOUR_MS, HISTORY_MS) == {"sensors": [], "seen": {}}
        assert store.positions(CO2) == {}
        HistoryStore(store.path)  # reouverture : schema deja en place


class TestInsert:
    def test_keeps_numeric_dated_measurements_only(self, store):
        brut = make_record(offset=5)
        brut["value"] = "texte brut"
        skipped = [
            make_measurement("400", offset=1),
            make_measurement(True, offset=2),
            make_measurement(400, offset=3, timestamp_ms=None),
            make_measurement(400, offset=None),
            brut,
        ]

        assert store.insert([*skipped,
                             make_measurement(400, offset=4, timestamp_ms=NOW)]) == 1

        (sensor,) = store.load(NOW, HOUR_MS, HISTORY_MS)["sensors"]
        assert sensor["points"] == [[NOW, 400.0]]
        # Prefixe consomme : les records non archives avancent aussi le curseur
        assert store.positions("t") == {0: 5}

    def test_duplicate_offset_counted_once(self, store):
        first = make_measurement(400, offset=7, timestamp_ms=NOW)
        again = make_measurement(999, offset=7, timestamp_ms=NOW + 1)
        assert store.insert([first]) == 1

        assert store.insert([again, first]) == 0

        assert rows(store, "SELECT count, sum FROM hourly") == [(1, 400.0)]
        (sensor,) = store.load(NOW, HOUR_MS, HISTORY_MS)["sensors"]
        assert sensor["record"] == first
        assert sensor["points"] == [[NOW, 400.0]]

    def test_load_points_hours_latest_and_seen(self, store):
        hour = NOW - NOW % HOUR_MS
        store.insert([
            make_measurement(3, offset=12, timestamp_ms=hour + 2, zone="Zone B"),
            make_measurement(1, offset=10, timestamp_ms=hour + 1),
            make_measurement(2, offset=11, timestamp_ms=hour, partition=1),
            make_measurement(50, offset=1, timestamp_ms=hour - HOUR_MS),  # hors points
            make_measurement(60, offset=0, timestamp_ms=hour - 3 * HOUR_MS),  # hors heures
            make_measurement(7, offset=3, timestamp_ms=hour, node_id="n2",
                             topic="autre"),
        ])

        data = store.load(hour + 10, raw_ms=HOUR_MS, history_ms=2 * HOUR_MS)

        assert data["seen"] == {"t": {"0": [[0, 12]], "1": [[0, 11]]},
                                "autre": {"0": [[0, 3]]}}
        by_id = {(s["topic"], s["id"]): s for s in data["sensors"]}
        n1 = by_id[("t", "n1")]
        # Dernier record : le plus recent par horodatage, pas le dernier insere
        assert n1["record"]["value"]["metadata"]["zone"]["label"] == "Zone B"
        assert n1["points"] == [[hour, 2.0], [hour + 1, 1.0], [hour + 2, 3.0]]
        assert n1["hours"] == {str(hour - HOUR_MS): [1, 50.0, 50.0, 50.0],
                               str(hour): [3, 6.0, 1.0, 3.0]}
        assert by_id[("autre", "n2")]["points"] == [[hour, 7.0]]

    def test_purge_once_per_hour(self, tmp_path):
        clock = [NOW]
        store = HistoryStore(tmp_path / "h.sqlite", retention_ms=2 * HOUR_MS,
                             clock=lambda: clock[0])
        store.insert([make_measurement(1, offset=0, timestamp_ms=NOW - 3 * HOUR_MS),
                      make_measurement(2, offset=1, timestamp_ms=NOW)])
        # Pas de purge avant une heure de fonctionnement
        assert rows(store, "SELECT count(*) FROM measurement") == [(2,)]

        clock[0] = NOW + 61 * 60_000
        store.insert([make_measurement(3, offset=2, timestamp_ms=NOW - 3 * HOUR_MS)])
        # Purge : mesures et heures plus vieilles que la retention
        assert rows(store, "SELECT offset FROM measurement") == [(1,)]
        assert rows(store, "SELECT count(*) FROM hourly") == [(1,)]

        clock[0] = NOW + 71 * 60_000
        store.insert([make_measurement(4, offset=3, timestamp_ms=NOW - 3 * HOUR_MS)])
        # Pas de nouvelle purge dans l'heure qui suit
        assert rows(store, "SELECT count(*) FROM measurement") == [(2,)]

    async def test_concurrent_inserts_from_threads(self, store):
        batches = [[make_measurement(i, offset=i, timestamp_ms=NOW + i)]
                   for i in range(20)]

        await asyncio.gather(*[asyncio.to_thread(store.insert, b) for b in batches])

        assert rows(store, "SELECT count(*) FROM measurement") == [(20,)]
        assert store.positions("t") == {0: 19}
