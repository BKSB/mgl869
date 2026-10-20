"""Jumeau numerique : dernier etat et historique glissant de chaque capteur,
situe dans sa piece ; logique pure, sans asyncio ni I/O."""

import bisect
from dataclasses import dataclass, field

from app.data_management.data_processing.alert_rules import is_number
from app.data_management.records import sensor_id

HISTORY_MS = 24 * 3_600_000
NO_PLACE_ID = "_sans_piece"


@dataclass(frozen=True)
class Place:
    """Piece d'un capteur : zone, sinon espace (meme priorite que la
    `location` des alertes), avec etage et batiment."""
    id: str
    name: str
    floor: str = ""
    building: str = ""


UNKNOWN_PLACE = Place(NO_PLACE_ID, "Sans pièce")


def _label(metadata: dict, key: str) -> str:
    entry = metadata.get(key)
    label = entry.get("label") if isinstance(entry, dict) else None
    return label if isinstance(label, str) else ""


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
                         building=_label(metadata, "building"))
    return UNKNOWN_PLACE


@dataclass
class SensorTwin:
    topic: str
    id: str
    place: Place
    unit: str
    value: float
    updated_ms: int
    # (t, v) tries par t ; fenetre glissante purgee a chaque mesure
    points: list[tuple[int, float]] = field(default_factory=list)

    def window(self, since_ms: int) -> list[tuple[int, float]]:
        return self.points[bisect.bisect_left(self.points, (since_ms,)):]


class DigitalTwin:
    def __init__(self, history_ms: int = HISTORY_MS) -> None:
        self._history_ms = history_ms
        self._sensors: dict[tuple[str, str], SensorTwin] = {}

    def ingest(self, topic: str, record: dict, now_ms: int) -> bool:
        """Faux si le record ne porte pas de mesure numerique datee, ou plus
        vieille que l'historique. Metadonnees et valeur courante : celles de
        la mesure la plus recente, quel que soit l'ordre d'arrivee."""
        payload = record.get("value")
        if not isinstance(payload, dict):
            return False
        value, at_ms = payload.get("value"), record.get("timestamp_ms")
        if not is_number(value) or not isinstance(at_ms, int) \
                or isinstance(at_ms, bool) or at_ms < now_ms - self._history_ms:
            return False
        unit = payload.get("unit")
        unit = unit if isinstance(unit, str) else ""
        key = (topic, sensor_id(record))
        sensor = self._sensors.get(key)
        if sensor is None:
            sensor = self._sensors[key] = SensorTwin(
                topic, key[1], place_from(payload), unit, float(value), at_ms)
        elif at_ms >= sensor.updated_ms:
            sensor.value, sensor.updated_ms = float(value), at_ms
            sensor.unit, sensor.place = unit, place_from(payload)
        bisect.insort(sensor.points, (at_ms, float(value)))
        expired = bisect.bisect_left(sensor.points, (now_ms - self._history_ms,))
        if expired:
            del sensor.points[:expired]
        return True

    def sensors(self) -> list[SensorTwin]:
        return list(self._sensors.values())

    def sensor(self, topic: str, sensor_id: str) -> SensorTwin | None:
        return self._sensors.get((topic, sensor_id))
