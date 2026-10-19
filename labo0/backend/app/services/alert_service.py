"""Observateur du bus : etat d'alerte par capteur, idempotence et diffusion
WebSocket ; l'evaluation pure vit dans data_processing/alert_rules.py."""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field

from app.config import AlertsConfig
from app.data_management.data_distribution.queues import offer_or_reset
from app.data_management.data_processing.alert_rules import (
    DEESCALATED,
    ESCALATED,
    RAISED,
    RESOLVED,
    SEVERITY_RANK,
    AlertEvent,
    AlertRule,
    SensorState,
    evaluate,
    measurement_from_record,
)

logger = logging.getLogger(__name__)

_LOG_LEVELS = {
    RAISED: logging.WARNING,
    ESCALATED: logging.WARNING,
    DEESCALATED: logging.INFO,
    RESOLVED: logging.INFO,
}


@dataclass
class _SensorTracker:
    state: SensorState = field(default_factory=SensorState)
    # Derniere mesure evaluee
    last_ms: int | None = None
    last_partition: object = None

    def accept(self, partition: object, timestamp_ms: int) -> bool:
        """Faux pour une mesure plus ancienne venue d'une AUTRE partition :
        elle ramenerait l'etat en arriere. Dans une meme partition l'offset
        fait foi : un horodatage en recul ou futur ne fige pas le capteur."""
        if (self.last_ms is not None and partition != self.last_partition
                and timestamp_ms < self.last_ms):
            return False
        self.last_ms = timestamp_ms
        self.last_partition = partition
        return True


class AlertService:
    """Une alerte au plus par capteur et topic. Aucun await dans on_record :
    un nouvel abonne recoit un snapshot coherent, puis chaque evenement."""

    RECENT_SIZE = 200
    # Au-dela : snapshot a la place des messages en attente (offer_or_reset)
    CLIENT_QUEUE_SIZE = 1000

    def __init__(self, config: AlertsConfig) -> None:
        self._enabled = config.enabled
        self._rules: dict[str, tuple[AlertRule, ...]] = (
            {topic: tuple(rules) for topic, rules in config.rules.items()
             if rules}
            if config.enabled else {})
        self._sensors: dict[tuple[str, str], _SensorTracker] = {}
        # Plus haut offset evalue par (topic, partition)
        self._offsets: dict[tuple[str, object], int] = {}
        self._recent: deque[AlertEvent] = deque(maxlen=self.RECENT_SIZE)
        self._subscribers: set[asyncio.Queue] = set()
        if self._enabled:
            logger.info("Alertes actives : %d regle(s) sur %d topic(s) (%s)",
                        sum(len(r) for r in self._rules.values()),
                        len(self._rules), config.source)

    # --- Observateur du bus -------------------------------------------------

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Rejoue : etat mis a jour sans evenement, pour reconstruire les
        alertes actives au redemarrage sans les redeclencher ; un changement
        de niveau envoie un snapshot (rien d'historise ni de journalise)."""
        rules = self._rules.get(topic)
        if not rules:
            return
        measurement = measurement_from_record(topic, record)
        if measurement is None or not self._mark_evaluated(topic, record):
            return
        key = (topic, measurement.node_id)
        tracker = self._sensors.get(key)
        if tracker is None:
            tracker = self._sensors[key] = _SensorTracker()
        partition = record.get("partition")
        if not tracker.accept(partition, measurement.timestamp_ms):
            logger.debug("[%s] mesure ignoree pour le capteur %s : partition "
                         "%s, plus ancienne que la derniere evaluee",
                         topic, measurement.node_id, partition)
            return

        tracker.state, events = evaluate(rules, measurement, tracker.state)
        if not events:
            return
        if replay:
            self._send(self._snapshot())
        else:
            for event in events:
                self._emit(event)

    def _mark_evaluated(self, topic: str, record: dict) -> bool:
        """Faux si deja evalue : livraison au moins une fois, et prechauffage
        et consommateur peuvent lire les memes records."""
        offset = record.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool):
            return True  # sans offset, aucune relecture n'est detectable
        key = (topic, record.get("partition"))
        last = self._offsets.get(key)
        if last is not None and offset <= last:
            return False
        self._offsets[key] = offset
        return True

    def _emit(self, event: AlertEvent) -> None:
        self._recent.appendleft(event)
        alert = event.alert
        logger.log(_LOG_LEVELS[event.kind],
                   "[%s] alerte %s (%s) capteur %s%s : %s %s %s, valeur %s",
                   alert.topic, event.kind, alert.severity, alert.node_id,
                   f" ({alert.location})" if alert.location else "",
                   alert.direction, alert.threshold, alert.unit, alert.value)
        self._send({"type": "event", "event": event.to_dict()})

    def _snapshot(self) -> dict:
        return {"type": "snapshot", "active": self.active()}

    def _send(self, message: dict) -> None:
        for queue in self._subscribers:
            offer_or_reset(queue, message, self._snapshot)

    # --- Requetes de la couche API ------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def rules(self) -> dict[str, list[dict]]:
        return {topic: [rule.to_dict() for rule in rules]
                for topic, rules in self._rules.items()}

    def active(self) -> list[dict]:
        """Critical d'abord, puis de la plus ancienne a la plus recente."""
        alerts = sorted(
            (t.state.alert for t in self._sensors.values()
             if t.state.alert is not None),
            key=lambda a: (-SEVERITY_RANK[a.severity], a.since_ms, a.id))
        return [alert.to_dict() for alert in alerts]

    def recent(self) -> list[dict]:
        """Le plus recent d'abord."""
        return [event.to_dict() for event in self._recent]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.CLIENT_QUEUE_SIZE)
        queue.put_nowait(self._snapshot())
        self._subscribers.add(queue)
        logger.info("Client WebSocket abonne aux alertes (%d connecte(s))",
                    len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
