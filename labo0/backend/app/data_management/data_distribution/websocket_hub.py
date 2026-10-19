"""Diffusion des records vers les clients WebSocket, un canal par topic.
subscribe et publish sont sans await : atomiques dans la boucle asyncio."""

import asyncio
import logging
from collections import deque

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.records import sensor_id

logger = logging.getLogger(__name__)


def _dedup_key(record: dict) -> tuple:
    return record.get("partition"), record.get("offset")


class TopicHub:
    """Historique par capteur : un capteur bavard n'evince pas les autres."""

    # Au-dela du rejeu : absorbe le temps reel d'un client lent avant eviction
    CLIENT_QUEUE_MARGIN = 1000

    def __init__(self, history_per_sensor: dict[str, int] | None = None,
                 default_history: int = 100) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # topic -> capteur -> derniers records
        self._history: dict[str, dict[str, deque]] = {}
        # Cles (partition, offset) de chaque deque : deduplication en O(1)
        self._keys: dict[tuple[str, str], set[tuple]] = {}
        self._history_sizes = history_per_sensor or {}
        self._default_history = default_history

    def subscribe(self, topic: str) -> asyncio.Queue:
        sensors = self._history.get(topic, {})
        replay = [r for records in sensors.values() for r in records]
        # Fusion par date ; file dimensionnee pour tout le rejeu, plus la marge
        replay.sort(key=lambda r: r.get("timestamp_ms") or 0)
        queue: asyncio.Queue = asyncio.Queue(
            maxsize=len(replay) + self.CLIENT_QUEUE_MARGIN)
        for record in replay:
            queue.put_nowait(record)
        self._subscribers.setdefault(topic, set()).add(queue)
        logger.info("[%s] client WebSocket abonne (%d connecte(s), %d message(s) "
                    "rejoue(s) pour %d capteur(s))",
                    topic, len(self._subscribers[topic]), len(replay), len(sensors))
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        self._subscribers.get(topic, set()).discard(queue)

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Rejoue ou non, meme traitement : le prechauffage remplit
        l'historique. Idempotent grace a la deduplication de publish."""
        self.publish(topic, record)

    def publish(self, topic: str, record: dict) -> None:
        sensor = sensor_id(record)
        key = _dedup_key(record)
        size = self._history_sizes.get(topic, self._default_history)
        records = self._history.setdefault(topic, {}).setdefault(
            sensor, deque(maxlen=size)
        )
        keys = self._keys.setdefault((topic, sensor), set())
        # Deja vu : prechauffage et reprise sur offset commite se recouvrent
        if key in keys:
            return
        # Copie (record partage entre observateurs) ; sensor_id : les clients
        # n'ont pas a redefinir l'identite du capteur
        record = {**record, "sensor_id": sensor}
        if records and len(records) == records.maxlen:
            keys.discard(_dedup_key(records[0]))  # evince par l'ajout
        records.append(record)
        # Historique de taille 0 : aucune cle a retenir
        if records.maxlen:
            keys.add(key)
        for queue in self._subscribers.get(topic, ()):
            offer_dropping_oldest(queue, record)
