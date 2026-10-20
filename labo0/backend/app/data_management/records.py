"""Record (record_from_msg) : { topic, partition, offset, timestamp_ms, key,
value } ; value : payload JSON { node_id, type, value, unit, metadata }, une
chaine (non JSON) ou None."""

NO_SENSOR_ID = "_sans_node_id"


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
