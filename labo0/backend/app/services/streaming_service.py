"""Couche service : orchestre l'acquisition (consommateurs Kafka) et la
distribution (bus de records et ses observateurs, dont le hub WebSocket).
Point d'entree de la couche API vers les flux de donnees (les alertes ont
le leur, l'AlertService) -- l'API ne connait ni Kafka, ni le hub, ni les
taches."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.config import Settings
from app.data_management.data_acquisition.consumer import consume_topic
from app.data_management.data_acquisition.history_warmup import warmup_topic
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus

logger = logging.getLogger(__name__)


class StreamingService:

    # Un record horodate plus de 5 min avant le demarrage du service est un
    # rattrapage (retard accumule pendant un arret, ou toute la retention
    # quand le groupe n'a pas d'offset commite) : il est publie comme rejoue.
    # Les records d'un arret plus court restent du temps reel.
    BACKLOG_GRACE_MS = 5 * 60_000

    def __init__(self, settings: Settings, hub: TopicHub,
                 bus: RecordBus) -> None:
        """`bus` : bus de records sur lequel l'acquisition publie, construit
        par le composition root, qui y inscrit les observateurs dans l'ordre
        voulu. Le service y inscrit lui-meme le hub, dont dependent ses
        abonnements WebSocket (sans effet s'il l'est deja)."""
        self._settings = settings
        self._hub = hub
        self._bus = bus
        bus.subscribe(hub)
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

        # Regles d'alerte : contenu invalide ou topic non consomme
        errors.extend(self._settings.alerts.validate(self._settings.topics))

        return errors

    def _replay_publisher(self, topic: str) -> Callable[[dict], Awaitable[None]]:
        """Callback du prechauffage (fonction coroutine) : publie sur le bus
        chaque record d'UN topic comme rejoue (replay=True). `topic` est fige
        a la creation : pas de piege de liaison tardive sur la variable de
        boucle de `start`."""
        async def publish(record: dict) -> None:
            await self._bus.publish(topic, record, replay=True)
        return publish

    def _live_publisher(self, topic: str,
                        live_since_ms: int) -> Callable[[dict], Awaitable[None]]:
        """Callback du consommateur d'UN topic : un record horodate avant
        `live_since_ms` est un rattrapage, publie comme rejoue (replay=True) ;
        les suivants sont du temps reel (replay=False)."""
        async def publish(record: dict) -> None:
            timestamp = record.get("timestamp_ms")
            backlog = isinstance(timestamp, int) and timestamp < live_since_ms
            await self._bus.publish(topic, record, replay=backlog)
        return publish

    def start(self) -> None:
        """Lance une tache de consommation par topic (et le prechauffage
        d'historique), chacune publiant les records de son topic sur le bus.
        Le prechauffage publie comme rejoue (replay=True) ; le consommateur
        aussi pour un record anterieur de plus de BACKLOG_GRACE_MS au
        demarrage, puis en temps reel (replay=False)."""
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
            self._consumers[topic] = asyncio.create_task(
                consume_topic(
                    topic=topic,
                    consumer_config=self._settings.consumer_config(topic),
                    output_dir=self._settings.output_dir,
                    on_record=self._live_publisher(topic, live_since_ms),
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
