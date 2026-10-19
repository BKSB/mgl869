"""Helpers partages sur les records Kafka.

Un record a la forme produite par `record_from_msg` :
{ topic, partition, offset, timestamp_ms, key, value }, ou `value` est le
payload JSON du capteur ({ node_id, type, value, unit, metadata }), une
chaine (message non JSON) ou None.
"""

# Identifiant de repli d'un record sans node_id ni cle Kafka
NO_SENSOR_ID = "_sans_node_id"


def sensor_id(record: dict) -> str:
    """Identifiant du capteur : node_id du payload, sinon la cle Kafka.

    Seule definition de l'identite d'un capteur : le hub WebSocket (historique
    par capteur) et le service d'alertes (une alerte par capteur) doivent
    designer le meme capteur."""
    value = record.get("value")
    if isinstance(value, dict) and value.get("node_id"):
        return str(value["node_id"])
    return record.get("key") or NO_SENSOR_ID
