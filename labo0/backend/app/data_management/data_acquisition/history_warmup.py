"""Prechauffage de l'historique au demarrage.

Le tampon d'historique par capteur vit en memoire : apres un redemarrage il
est vide, et les topics lents (ex. CO2) n'offrent aucun historique aux
clients WebSocket pendant longtemps. Cette coroutine relit la fin de chaque
partition du topic (les N derniers messages) avec un consommateur sans
groupe -- aucun commit, aucune ecriture JSONL -- et publie les records sur
le bus de records (comme rejoues, replay=True) : le hub, observateur du bus,
remplit ainsi ses tampons par capteur, et le service d'alertes reconstruit
ses alertes actives sans les declencher de nouveau.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer

from app.data_management.data_acquisition.consumer import record_from_msg

logger = logging.getLogger(__name__)

TIMEOUT_S = 20.0


async def warmup_topic(topic: str, consumer_config: dict,
                       publish: Callable[[dict], Awaitable[None]],
                       tail_per_partition: int) -> None:
    """Relit la fin d'un topic et publie chaque record via la coroutine
    `publish`."""
    # group_id=None (via consumer_config sans topic) : mode sans groupe,
    # toutes les partitions du topic sont assignees au demarrage
    consumer = AIOKafkaConsumer(topic, **consumer_config)
    try:
        await consumer.start()
        await _read_tail(consumer, topic, publish, tail_per_partition)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("[%s] echec du prechauffage d'historique", topic)
    finally:
        await consumer.stop()


async def _read_tail(consumer: AIOKafkaConsumer, topic: str,
                     publish: Callable[[dict], Awaitable[None]],
                     tail_per_partition: int) -> None:
    partitions = consumer.assignment()
    if not partitions:
        logger.warning("[%s] prechauffage : aucune partition assignee", topic)
        return

    begins = await consumer.beginning_offsets(partitions)
    ends = await consumer.end_offsets(partitions)

    # Position de depart : `fin - N` sur chaque partition (borne par le debut)
    targets = {}
    for tp in partitions:
        start = max(begins[tp], ends[tp] - tail_per_partition)
        consumer.seek(tp, start)
        if start < ends[tp]:
            targets[tp] = ends[tp]
    if not targets:
        logger.info("[%s] prechauffage : topic vide", topic)
        return

    count = 0
    remaining = set(targets)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT_S
    while remaining and loop.time() < deadline:
        batches = await consumer.getmany(timeout_ms=500, max_records=500)
        for tp, messages in batches.items():
            for msg in messages:
                await publish(record_from_msg(msg))
                count += 1
                if msg.offset >= targets.get(tp, 0) - 1:
                    remaining.discard(tp)
    logger.info("[%s] prechauffage : %d message(s) d'historique recharges",
                topic, count)
