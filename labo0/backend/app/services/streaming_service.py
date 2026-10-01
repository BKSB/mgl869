"""Couche service : orchestre l'acquisition (consommateurs Kafka) et la
distribution (hub WebSocket). Seul point d'entree de la couche API vers les
donnees -- l'API ne connait ni Kafka, ni le hub, ni les taches."""

import asyncio
import logging
from pathlib import Path

from app.config import Settings
from app.data_management.data_acquisition.consumer import consume_topic
from app.data_management.data_acquisition.history_warmup import warmup_topic
from app.data_management.data_distribution.websocket_hub import TopicHub

logger = logging.getLogger(__name__)


class StreamingService:

    def __init__(self, settings: Settings, hub: TopicHub) -> None:
        self._settings = settings
        self._hub = hub
        self._consumers: dict[str, asyncio.Task] = {}
        self._warmups: list[asyncio.Task] = []

    # --- Cycle de vie -----------------------------------------------------

    def validate(self) -> list[str]:
        """Verifie la configuration avant demarrage ; retourne les erreurs."""
        errors = []
        protocol = self._settings.security_protocol.upper()

        if protocol in ("SSL", "SASL_SSL") and \
                not Path(self._settings.ssl_ca_location).is_file():
            errors.append(f"Certificat CA introuvable : {self._settings.ssl_ca_location}")

        if protocol.startswith("SASL") and \
                not (self._settings.sasl_username and self._settings.sasl_password):
            errors.append("KAFKA_USERNAME / KAFKA_PASSWORD requis avec le "
                          f"protocole {self._settings.security_protocol}")

        if not self._settings.topics:
            errors.append("Aucun topic configure (config/topics.yaml)")

        return errors

    def start(self) -> None:
        """Lance une tache de consommation par topic (et le prechauffage
        d'historique), chacune publiant vers le canal WebSocket de son topic."""
        for topic_cfg in self._settings.topic_configs:
            topic = topic_cfg.name
            publish = (lambda record, _topic=topic:
                       self._hub.publish(_topic, record))
            if topic_cfg.warmup_messages > 0:
                self._warmups.append(asyncio.create_task(
                    warmup_topic(
                        topic=topic,
                        consumer_config=self._settings.consumer_config(),
                        publish=publish,
                        tail_per_partition=topic_cfg.warmup_messages,
                    ),
                    name=f"warmup-{topic}",
                ))
            self._consumers[topic] = asyncio.create_task(
                consume_topic(
                    topic=topic,
                    consumer_config=self._settings.consumer_config(topic),
                    output_dir=self._settings.output_dir,
                    on_record=publish,
                ),
                name=f"consumer-{topic}",
            )
        logger.info("Demarrage : %d topic(s) sur %s (protocole %s)",
                    len(self._settings.topics), self._settings.bootstrap_servers,
                    self._settings.security_protocol)

    async def stop(self) -> None:
        tasks = [*self._warmups, *self._consumers.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Service arrete")

    async def watch_consumers(self) -> None:
        """Signale dans les logs tout consommateur arrete inopinement."""
        reported: set[str] = set()
        while True:
            await asyncio.sleep(5)
            for topic, task in self._consumers.items():
                if task.done() and topic not in reported:
                    exc = task.exception() if not task.cancelled() else None
                    logger.error("Consommateur arrete inopinement : %s (%r)",
                                 topic, exc)
                    reported.add(topic)

    # --- Requetes de la couche API ---------------------------------------

    def topics(self) -> list[str]:
        return list(self._settings.topics)

    def is_known_topic(self, topic: str) -> bool:
        return topic in self._settings.topics

    def subscribe(self, topic: str) -> asyncio.Queue:
        """Abonne un client au flux d'un topic ; retourne sa file de messages
        (pre-remplie avec l'historique par capteur)."""
        return self._hub.subscribe(topic)

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        self._hub.unsubscribe(topic, queue)

    def health(self) -> dict:
        consumers = {t: not task.done() for t, task in self._consumers.items()}
        return {
            "status": "ok" if all(consumers.values()) else "degraded",
            "consumers": consumers,
        }
