"""Jumeau numerique : dernier etat, points bruts recents et agregats horaires
de chaque capteur, situe dans sa piece ; logique pure, sans asyncio ni I/O."""

import bisect
from dataclasses import asdict, dataclass, field

from app.data_management.data_processing.alert_rules import is_number
from app.data_management.records import SeenOffsets, sensor_id

HOUR_MS = 3_600_000
# Points bruts (tuiles, plage 24 h du graphe) ; au-dela : une case par heure
RAW_MS = 24 * HOUR_MS
HISTORY_MS = 30 * 24 * HOUR_MS
NO_PLACE_ID = "_sans_piece"


@dataclass(frozen=True)
class Place:
    """Piece d'un capteur : zone, sinon espace (meme priorite que la
    `location` des alertes), avec etage, batiment et local (space.id,
    ex. « A-1540 »)."""
    id: str
    name: str
    floor: str = ""
    building: str = ""
    space: str = ""


UNKNOWN_PLACE = Place(NO_PLACE_ID, "Sans pièce")


def _label(metadata: dict, key: str) -> str:
    entry = metadata.get(key)
    label = entry.get("label") if isinstance(entry, dict) else None
    return label if isinstance(label, str) else ""


def _id_or_label(metadata: dict, key: str) -> str:
    entry = metadata.get(key)
    ident = entry.get("id") if isinstance(entry, dict) else None
    return str(ident) if ident else _label(metadata, key)


def place_from(payload: dict) -> Place:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return UNKNOWN_PLACE
    for key in ("zone", "space"):
        entry = metadata.get(key)
        if not isinstance(entry, dict):
            continue
        ident, label = entry.get("id"), _label(metadata, key)
        name = label or (str(ident) if ident else "")
        if name:
            return Place(id=str(ident) if ident else name, name=name,
                         floor=_label(metadata, "storey"),
                         building=_label(metadata, "building"),
                         space=_id_or_label(metadata, "space"))
    return UNKNOWN_PLACE


# Case d'agregation : [nombre, somme, min, max]
Bucket = list[float]


def add_to_bucket(bucket: Bucket | None, value: float) -> Bucket:
    if bucket is None:
        return [1, value, value, value]
    bucket[0] += 1
    bucket[1] += value
    bucket[2] = min(bucket[2], value)
    bucket[3] = max(bucket[3], value)
    return bucket


@dataclass
class SensorTwin:
    topic: str
    id: str
    place: Place
    unit: str
    value: float
    updated_ms: int
    # (t, v) tries par t, RAW_MS glissantes
    points: list[tuple[int, float]] = field(default_factory=list)
    # debut d'heure (ms) -> Bucket, HISTORY_MS glissantes
    hours: dict[int, Bucket] = field(default_factory=dict)
    seen: SeenOffsets = field(default_factory=SeenOffsets)

    def window(self, since_ms: int) -> list[tuple[int, float]]:
        return self.points[bisect.bisect_left(self.points, (since_ms,)):]

    def hours_since(self, since_ms: int) -> list[tuple[int, Bucket]]:
        return sorted((h, b) for h, b in self.hours.items() if h >= since_ms)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic, "id": self.id, "place": asdict(self.place),
            "unit": self.unit, "value": self.value, "updated_ms": self.updated_ms,
            "points": [list(p) for p in self.points],
            "hours": {str(h): b for h, b in self.hours.items()},
            "seen": self.seen.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SensorTwin":
        return cls(
            topic=data["topic"], id=data["id"], place=Place(**data["place"]),
            unit=data["unit"], value=float(data["value"]),
            updated_ms=int(data["updated_ms"]),
            points=sorted((int(t), float(v)) for t, v in data["points"]),
            hours={int(h): [float(x) for x in b] for h, b in data["hours"].items()},
            seen=SeenOffsets(data["seen"]),
        )


class DigitalTwin:
    def __init__(self, history_ms: int = HISTORY_MS, raw_ms: int = RAW_MS) -> None:
        self._history_ms = history_ms
        self._raw_ms = raw_ms
        self._sensors: dict[tuple[str, str], SensorTwin] = {}

    def ingest(self, topic: str, record: dict, now_ms: int) -> bool:
        """Faux si le record ne porte pas de mesure numerique datee, est plus
        vieux que l'historique ou a deja ete vu (offset). Metadonnees et
        valeur courante : celles de la mesure la plus recente, quel que soit
        l'ordre d'arrivee."""
        payload = record.get("value")
        if not isinstance(payload, dict):
            return False
        value, at_ms = payload.get("value"), record.get("timestamp_ms")
        if not is_number(value) or not isinstance(at_ms, int) \
                or isinstance(at_ms, bool) or at_ms < now_ms - self._history_ms:
            return False
        value = float(value)
        unit = payload.get("unit")
        unit = unit if isinstance(unit, str) else ""
        key = (topic, sensor_id(record))
        sensor = self._sensors.get(key)
        if sensor is None:
            sensor = self._sensors[key] = SensorTwin(
                topic, key[1], place_from(payload), unit, value, at_ms)
        offset = record.get("offset")
        if isinstance(offset, int) and not isinstance(offset, bool) \
                and not sensor.seen.add(record.get("partition"), offset):
            return False
        if at_ms >= sensor.updated_ms:
            sensor.value, sensor.updated_ms = value, at_ms
            sensor.unit, sensor.place = unit, place_from(payload)
        if at_ms >= now_ms - self._raw_ms:
            bisect.insort(sensor.points, (at_ms, value))
        hour = at_ms - at_ms % HOUR_MS
        sensor.hours[hour] = add_to_bucket(sensor.hours.get(hour), value)
        self._expire(sensor, now_ms)
        return True

    def _expire(self, sensor: SensorTwin, now_ms: int) -> None:
        expired = bisect.bisect_left(sensor.points, (now_ms - self._raw_ms,))
        if expired:
            del sensor.points[:expired]
        cutoff = now_ms - self._history_ms
        for hour in [h for h in sensor.hours if h < cutoff]:
            del sensor.hours[hour]

    def sensors(self) -> list[SensorTwin]:
        return list(self._sensors.values())

    def sensor(self, topic: str, sensor_id: str) -> SensorTwin | None:
        return self._sensors.get((topic, sensor_id))

    # --- Instantane (persistance de l'historique entre deux demarrages) -----

    def to_dict(self) -> dict:
        return {"sensors": [s.to_dict() for s in self._sensors.values()]}

    def restore(self, data: dict, now_ms: int) -> int:
        """Charge un instantane (entrees invalides ignorees) ; nombre de
        capteurs restaures."""
        count = 0
        for entry in data.get("sensors", ()):
            try:
                sensor = SensorTwin.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                continue
            self._expire(sensor, now_ms)
            self._sensors[(sensor.topic, sensor.id)] = sensor
            count += 1
        return count
