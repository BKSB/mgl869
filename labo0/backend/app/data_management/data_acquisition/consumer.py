"""Consommateur Kafka d'un topic : une tache asyncio dans la boucle du
serveur WebSocket, sans pont entre threads. Reprend la ou l'archive
s'arrete, puis archive, notifie et commite lot par lot."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer

from app.data_management.data_storage.history_store import HistoryStore

logger = logging.getLogger(__name__)

# Taille maximale d'un lot, et attente maximale avant un lot vide
BATCH_SIZE = 500
POLL_MS = 1000


def record_from_msg(msg) -> dict:
    """Seule forme du record : archive, flux WebSocket et suiveur."""
    raw = msg.value.decode("utf-8", errors="replace") if msg.value else None
    try:
        value = json.loads(raw) if raw is not None else None
    except json.JSONDecodeError:
        value = raw
    return {
        "topic": msg.topic,
        "partition": msg.partition,
        "offset": msg.offset,
        "timestamp_ms": msg.timestamp,
        "key": msg.key.decode("utf-8", errors="replace") if msg.key else None,
        "value": value,
    }


async def _seek_after_archive(consumer: AIOKafkaConsumer, topic: str,
                              store: HistoryStore) -> None:
    """La base fait foi : chaque partition reprend apres son dernier offset
    archive ; sans curseur, depuis le debut de la retention Kafka."""
    positions = await asyncio.to_thread(store.positions, topic)
    for tp in consumer.assignment():
        if tp.partition in positions:
            consumer.seek(tp, positions[tp.partition] + 1)
        else:
            await consumer.seek_to_beginning(tp)


async def consume_topic(topic: str, consumer_config: dict, store: HistoryStore,
                        on_record: Callable[[dict], Awaitable[None]]) -> None:
    consumer = AIOKafkaConsumer(topic, **consumer_config)
    await consumer.start()  # partitions assignees au retour : seek possible
    try:
        await _seek_after_archive(consumer, topic, store)
        logger.info("[%s] abonne, en attente de messages", topic)
        while True:
            batches = await consumer.getmany(timeout_ms=POLL_MS,
                                             max_records=BATCH_SIZE)
            records = [record_from_msg(msg)
                       for messages in batches.values() for msg in messages]
            if not records:
                continue
            # Archive bloquante hors de la boucle, puis notification AVANT
            # commit : au moins une fois, un lot relu est deduplique partout
            await asyncio.to_thread(store.insert, records)
            for record in records:
                await on_record(record)
            await consumer.commit()
            logger.info("[%s] lot de %d message(s) archive et commite : %s",
                        topic, len(records), ", ".join(
                            f"partition={tp.partition} offset={msgs[-1].offset}"
                            for tp, msgs in batches.items()))
    finally:
        await consumer.stop()
        logger.info("[%s] consommateur ferme", topic)
