"""Consommateur Kafka asynchrone dedie a un seul topic.

Une tache asyncio par topic : les donnees de chaque topic sont recuperees et
traitees separement, dans la meme boucle d'evenements que le serveur
WebSocket (aucun pont inter-threads necessaire).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiokafka import AIOKafkaConsumer

logger = logging.getLogger(__name__)


def record_from_msg(msg) -> dict:
    """Convertit un message Kafka en record JSON-serialisable (forme commune
    au fichier JSONL, au flux WebSocket et au prechauffage d'historique)."""
    raw = msg.value.decode("utf-8", errors="replace") if msg.value else None
    try:
        value = json.loads(raw) if raw is not None else None
    except json.JSONDecodeError:
        value = raw  # message non JSON : conserve tel quel
    return {
        "topic": msg.topic,
        "partition": msg.partition,
        "offset": msg.offset,
        "timestamp_ms": msg.timestamp,
        "key": msg.key.decode("utf-8", errors="replace") if msg.key else None,
        "value": value,
    }


def _append_line(out, line: str) -> None:
    out.write(line)
    out.flush()


async def consume_topic(topic: str, consumer_config: dict, output_dir: str,
                        on_record: Callable[[dict], Awaitable[None]]) -> None:
    """Consomme un topic : chaque message est archive dans le fichier JSONL
    du topic puis transmis a la coroutine `on_record` (publication sur le bus
    de records, qui notifie tous les observateurs, dont le hub WebSocket).
    L'offset n'est commite qu'une fois `on_record` termine : un arret pendant
    le traitement fait relire le message (livraison "au moins une fois").
    S'arrete proprement sur annulation."""
    output_path = Path(output_dir) / f"{topic}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    consumer = AIOKafkaConsumer(topic, **consumer_config)
    await consumer.start()
    logger.info("[%s] abonne, en attente de messages", topic)
    try:
        with output_path.open("a", encoding="utf-8") as out:
            async for msg in consumer:
                record = record_from_msg(msg)
                line = json.dumps(record, ensure_ascii=False) + "\n"
                # Ecriture fichier bloquante : hors de la boucle asyncio,
                # pour ne jamais geler les autres topics ni les WebSockets
                await asyncio.to_thread(_append_line, out, line)
                # Notification AVANT commit : garantie "au moins une fois"
                await on_record(record)
                await consumer.commit()
                logger.info("[%s] partition=%d offset=%d recu",
                            msg.topic, msg.partition, msg.offset)
    finally:
        await consumer.stop()
        logger.info("[%s] consommateur ferme", topic)
