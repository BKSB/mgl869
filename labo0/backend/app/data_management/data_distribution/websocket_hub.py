"""Diffusion des messages Kafka vers les clients WebSocket.

Chaque topic a son propre canal : un client s'abonne au flux d'un seul topic
(endpoint /ws/<topic>). Consommateurs Kafka et handlers WebSocket vivent dans
la meme boucle asyncio : aucune synchronisation inter-threads n'est
necessaire, et entre deux `await` rien ne peut s'intercaler (l'abonnement et
la publication sont naturellement atomiques).

Le hub est un observateur du bus de records (app/data_management/record_bus.py) :
il recoit chaque record via `on_record`, sans dependre de l'acquisition.
"""

import asyncio
import logging
from collections import deque

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.records import sensor_id

logger = logging.getLogger(__name__)


class TopicHub:
    """Distribue les records aux files des clients WebSocket, par topic.

    L'historique est conserve PAR CAPTEUR (node_id) : chaque capteur garde
    ses derniers messages, si bien qu'un capteur tres bavard ne peut pas
    evincer l'historique d'un capteur plus lent. A la connexion, un client
    recoit l'historique de tous les capteurs du topic, fusionne par ordre
    chronologique, puis le flux temps reel."""

    # Marge de la file client au-dela du rejeu : absorbe le flux temps reel
    # d'un client lent avant eviction
    CLIENT_QUEUE_MARGIN = 1000

    def __init__(self, history_per_sensor: dict[str, int] | None = None,
                 default_history: int = 100) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # topic -> node_id -> deque des derniers messages de ce capteur
        self._history: dict[str, dict[str, deque]] = {}
        # Taille d'historique par topic (configurable via topics.yaml)
        self._history_sizes = history_per_sensor or {}
        self._default_history = default_history

    def subscribe(self, topic: str) -> asyncio.Queue:
        sensors = self._history.get(topic, {})
        replay = [r for records in sensors.values() for r in records]
        # Fusion chronologique de tous les capteurs ; la file est dimensionnee
        # pour contenir tout le rejeu plus une marge de flux temps reel
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
        """Observateur du bus de records (protocole RecordObserver).

        Les records rejoues (replay=True) sont traites comme les autres :
        remplir l'historique par capteur au demarrage est justement le role
        du prechauffage. La deduplication (partition, offset) de `publish`
        rend l'operation idempotente. Aucun `await` : la publication reste
        atomique vis-a-vis des abonnements WebSocket."""
        self.publish(topic, record)

    def publish(self, topic: str, record: dict) -> None:
        sensor = sensor_id(record)
        key = (record.get("partition"), record.get("offset"))
        size = self._history_sizes.get(topic, self._default_history)
        records = self._history.setdefault(topic, {}).setdefault(
            sensor, deque(maxlen=size)
        )
        # Deduplication : le prechauffage d'historique et la reprise sur
        # offsets commites peuvent relire le meme message
        if any((r.get("partition"), r.get("offset")) == key for r in records):
            return
        # Copie historisee et diffusee avec l'identifiant du capteur : les
        # clients regroupent les series (et retrouvent les alertes, dont le
        # node_id vient de la meme fonction) sans redefinir cette identite.
        # Le record partage avec les autres observateurs n'est pas modifie.
        record = {**record, "sensor_id": sensor}
        records.append(record)
        # Client trop lent : il perd ses messages les plus anciens plutot
        # que de bloquer les autres
        for queue in self._subscribers.get(topic, ()):
            offer_dropping_oldest(queue, record)
