"""Record (record_from_msg) : { topic, partition, offset, timestamp_ms, key,
value } ; value : payload JSON { node_id, type, value, unit, metadata }, une
chaine (non JSON) ou None."""

import bisect

NO_SENSOR_ID = "_sans_node_id"

HOUR_MS = 3_600_000
# Profondeur de l'historique, jumeau et archive : 30 jours glissants
HISTORY_MS = 30 * 24 * HOUR_MS


def sensor_id(record: dict) -> str:
    """Seule definition de l'identite d'un capteur (hub, alertes, clients)."""
    value = record.get("value")
    if isinstance(value, dict) and value.get("node_id"):
        return str(value["node_id"])
    return record.get("key") or NO_SENSOR_ID


class OffsetTracker:
    """Idempotence d'un observateur : livraison au moins une fois, et le
    prechauffage et le consommateur relisent les memes records."""

    def __init__(self) -> None:
        # Plus haut offset accepte par (topic, partition)
        self._last: dict[tuple[str, object], int] = {}

    def accept(self, topic: str, record: dict) -> bool:
        """Faux si l'offset ne depasse pas le plus haut deja vu sur sa partition."""
        offset = record.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool):
            return True  # sans offset, aucune relecture n'est detectable
        key = (topic, record.get("partition"))
        last = self._last.get(key)
        if last is not None and offset <= last:
            return False
        self._last[key] = offset
        return True


class SeenOffsets:
    """Offsets deja vus par partition, en intervalles fusionnes : prechauffage
    et rattrapage se recouvrent dans n'importe quel ordre, sans doublon et en
    memoire constante (contrairement a OffsetTracker, un offset plus ancien
    reste accepte)."""

    def __init__(self, ranges: dict[str, list[list[int]]] | None = None) -> None:
        # partition -> [[debut, fin], ...] tries, disjoints, non contigus
        self._ranges = ranges if ranges is not None else {}

    def add(self, partition: object, offset: int) -> bool:
        """Vrai si l'offset est nouveau (il est alors memorise)."""
        ranges = self._ranges.setdefault(str(partition), [])
        i = bisect.bisect_right(ranges, [offset + 1]) - 1  # dernier debut <= offset
        if i >= 0 and ranges[i][1] >= offset:
            return False
        left = i >= 0 and ranges[i][1] == offset - 1
        right = i + 1 < len(ranges) and ranges[i + 1][0] == offset + 1
        if left and right:
            ranges[i][1] = ranges[i + 1][1]
            del ranges[i + 1]
        elif left:
            ranges[i][1] = offset
        elif right:
            ranges[i + 1][0] = offset
        else:
            ranges.insert(i + 1, [offset, offset])
        return True

    def to_dict(self) -> dict[str, list[list[int]]]:
        return {p: [list(r) for r in ranges] for p, ranges in self._ranges.items()}
