"""Suiveur temps reel d'un topic, sans groupe, commit ni archive : relit la
queue de chaque partition (prechauffage, publie comme rejoue) puis publie
chaque nouveau message des son arrivee, jusqu'a ce que le consommateur du
topic ait rattrape le point de depart du suivi."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer

from app.data_management.data_acquisition.consumer import record_from_msg

logger = logging.getLogger(__name__)

TIMEOUT_S = 20.0

Publisher = Callable[[dict], Awaitable[None]]


async def follow_topic(topic: str, consumer_config: dict,
                       publish_replay: Publisher, publish_live: Publisher,
                       caught_up: Callable[[dict[int, int]], bool],
                       tail_per_partition: int) -> None:
    # group_id=None : aiokafka assigne toutes les partitions au demarrage
    consumer = AIOKafkaConsumer(topic, **consumer_config)
    try:
        await consumer.start()
        await _run(consumer, topic, publish_replay, publish_live, caught_up,
                   tail_per_partition)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("[%s] suivi temps reel interrompu", topic)
    finally:
        await consumer.stop()


async def _run(consumer: AIOKafkaConsumer, topic: str,
               publish_replay: Publisher, publish_live: Publisher,
               caught_up: Callable[[dict[int, int]], bool],
               tail_per_partition: int) -> None:
    partitions = consumer.assignment()
    if not partitions:
        logger.warning("[%s] suivi : aucune partition assignee", topic)
        return
    begins = await consumer.beginning_offsets(partitions)
    ends = await consumer.end_offsets(partitions)
    # Fins de partition au depart : limite de la queue, et point que le
    # consommateur doit atteindre pour prendre le relais
    targets = {tp: ends[tp] for tp in partitions if begins[tp] < ends[tp]}
    for tp in partitions:
        consumer.seek(tp, max(begins[tp], ends[tp] - tail_per_partition))
    if tail_per_partition > 0:
        await _read_tail(consumer, topic, publish_replay, targets)
    await _follow(consumer, topic, publish_live, caught_up,
                  {tp.partition: end for tp, end in targets.items()})


async def _read_tail(consumer: AIOKafkaConsumer, topic: str,
                     publish: Publisher, targets: dict) -> None:
    """Publie la queue jusqu'aux fins relevees, ou abandonne apres TIMEOUT_S."""
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


async def _follow(consumer: AIOKafkaConsumer, topic: str, publish: Publisher,
                  caught_up: Callable[[dict[int, int]], bool],
                  targets: dict[int, int]) -> None:
    """Temps reel tant que le consommateur n'a pas atteint les fins de
    partition relevees au depart ; ensuite il prend le relais seul."""
    while not caught_up(targets):
        batches = await consumer.getmany(timeout_ms=1000, max_records=500)
        for messages in batches.values():
            for msg in messages:
                await publish(record_from_msg(msg))
    logger.info("[%s] suivi temps reel termine : consommateur a jour", topic)
