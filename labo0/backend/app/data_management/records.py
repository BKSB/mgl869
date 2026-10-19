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
