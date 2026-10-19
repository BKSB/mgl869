"""Couche service : orchestre l'acquisition Kafka et le bus de records ;
l'API y accede aux flux sans connaitre Kafka, le hub ni les taches."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from functools import partial

from app.config import Settings
from app.data_management.data_acquisition.consumer import consume_topic
from app.data_management.data_acquisition.history_warmup import warmup_topic
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus

logger = logging.getLogger(__name__)


class StreamingService:

    # Record anterieur de plus de 5 min au demarrage : rattrapage (long arret,
    # groupe sans offset commite) publie comme rejoue ; en deca, temps reel
    BACKLOG_GRACE_MS = 5 * 60_000

    def __init__(self, settings: Settings, hub: TopicHub,
                 bus: RecordBus) -> None:
        """Hub requis sur le bus : il alimente les abonnements WebSocket."""
        if hub not in bus.observers:
            raise ValueError("le hub doit etre inscrit sur le bus de records "
                             "(voir app.main.create_bus)")
        self._settings = settings
        self._hub = hub
        self._bus = bus
        self._consumers: dict[str, asyncio.Task] = {}
        self._warmups: list[asyncio.Task] = []

    # --- Cycle de vie -----------------------------------------------------

    def _replay_publisher(self, topic: str) -> Callable[[dict], Awaitable[None]]:
        """Publie chaque record du prechauffage comme rejoue. Fermeture sur
        `topic` : pas de liaison tardive sur la variable de boucle de start."""
        async def publish(record: dict) -> None:
            await self._bus.publish(topic, record, replay=True)
        return publish

    def _live_publisher(self, topic: str,
                        live_since_ms: int) -> Callable[[dict], Awaitable[None]]:
        """Avant `live_since_ms` : rattrapage, publie comme rejoue."""
        async def publish(record: dict) -> None:
            timestamp = record.get("timestamp_ms")
            backlog = isinstance(timestamp, int) and timestamp < live_since_ms
            await self._bus.publish(topic, record, replay=backlog)
        return publish

    def start(self) -> None:
        # Limite du temps reel, figee au demarrage
        live_since_ms = int(time.time() * 1000) - self.BACKLOG_GRACE_MS
        for topic_cfg in self._settings.topic_configs:
            topic = topic_cfg.name
            if topic_cfg.warmup_messages > 0:
                self._warmups.append(asyncio.create_task(
                    warmup_topic(
                        topic=topic,
                        consumer_config=self._settings.consumer_config(),
                        publish=self._replay_publisher(topic),
                        tail_per_partition=topic_cfg.warmup_messages,
                    ),
                    name=f"warmup-{topic}",
                ))
            consumer = asyncio.create_task(
                consume_topic(
                    topic=topic,
                    consumer_config=self._settings.consumer_config(topic),
                    output_dir=self._settings.output_dir,
                    on_record=self._live_publisher(topic, live_since_ms),
                ),
                name=f"consumer-{topic}",
            )
            consumer.add_done_callback(partial(self._report_stopped, topic))
            self._consumers[topic] = consumer
        logger.info("Demarrage : %d topic(s) sur %s (protocole %s)",
                    len(self._settings.topics), self._settings.bootstrap_servers,
                    self._settings.security_protocol)

    async def stop(self) -> None:
        tasks = [*self._warmups, *self._consumers.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Service arrete")

    @staticmethod
    def _report_stopped(topic: str, task: asyncio.Task) -> None:
        if not task.cancelled():
            logger.error("Consommateur arrete inopinement : %s (%r)",
                         topic, task.exception())

    # --- Requetes de la couche API ---------------------------------------

    def topics(self) -> list[str]:
        return list(self._settings.topics)

    def is_known_topic(self, topic: str) -> bool:
        return topic in self._settings.topics

    def subscribe(self, topic: str) -> asyncio.Queue:
        return self._hub.subscribe(topic)

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        self._hub.unsubscribe(topic, queue)

    def health(self) -> dict:
        consumers = {t: not task.done() for t, task in self._consumers.items()}
        return {
            "status": "ok" if all(consumers.values()) else "degraded",
            "consumers": consumers,
        }
