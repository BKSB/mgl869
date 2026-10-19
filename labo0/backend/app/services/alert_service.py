"""Service d'alertes : observateur du bus de records qui evalue chaque mesure
contre les regles de son topic (config/alerts.yaml), tient la liste des
alertes actives et diffuse leurs changements (evenements) aux clients
WebSocket abonnes.

L'evaluation elle-meme (seuils, hysteresis, transitions, messages) est
pure et vit dans app/data_management/data_processing/alert_rules.py ; ce
service y ajoute l'etat par capteur, l'idempotence et la diffusion.
"""

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

# Niveau de journalisation de chaque evenement
_LOG_LEVELS = {
    RAISED: logging.WARNING,
    ESCALATED: logging.WARNING,
    DEESCALATED: logging.INFO,
    RESOLVED: logging.INFO,
}


@dataclass
class _SensorTracker:
    """Etat d'alerte d'un capteur et position de sa derniere mesure
    evaluee."""
    state: SensorState = field(default_factory=SensorState)
    # Horodatage et partition de la derniere mesure evaluee
    last_ms: int | None = None
    last_partition: object = None

    def in_order(self, partition: object, timestamp_ms: int) -> bool:
        """Vrai si la mesure doit etre evaluee (elle devient la derniere).

        Dans une meme partition, l'ordre des offsets fait foi : un horodatage
        qui recule (horloge corrigee) ou un record date du futur ne fige
        jamais l'evaluation du capteur. Seule une mesure arrivee par une
        AUTRE partition (capteur dont les records ne sont pas tous sur la
        meme) et plus ancienne que la derniere evaluee est ignoree : elle
        ramenerait l'etat en arriere."""
        if (self.last_ms is not None and partition != self.last_partition
                and timestamp_ms < self.last_ms):
            return False
        self.last_ms = timestamp_ms
        self.last_partition = partition
        return True


class AlertService:
    """Observateur du bus de records (protocole RecordObserver, typage
    structurel comme TopicHub) : une alerte au plus par capteur et topic.

    Tout s'execute dans la boucle asyncio, sans `await` dans `on_record` :
    evaluation, mise a jour des alertes actives et diffusion sont atomiques
    vis-a-vis des abonnements WebSocket (un nouvel abonne recoit un snapshot
    coherent, puis tous les evenements suivants)."""

    # Evenements recents conserves (le plus recent d'abord)
    RECENT_SIZE = 200
    # Capacite de la file d'un client WebSocket ; au-dela, un client trop
    # lent recoit un snapshot a la place de ses messages en attente (_send)
    CLIENT_QUEUE_SIZE = 1000

    def __init__(self, config: AlertsConfig) -> None:
        self._enabled = config.enabled
        self._rules: dict[str, tuple[AlertRule, ...]] = (
            {topic: tuple(rules) for topic, rules in config.rules.items()
             if rules}
            if config.enabled else {})
        self._sensors: dict[tuple[str, str], _SensorTracker] = {}
        # Plus haut offset evalue par (topic, partition) : chaque record n'est
        # evalue qu'une fois, dans l'ordre de sa partition, qu'il vienne du
        # prechauffage ou du consommateur
        self._offsets: dict[tuple[str, object], int] = {}
        self._recent: deque[AlertEvent] = deque(maxlen=self.RECENT_SIZE)
        self._subscribers: set[asyncio.Queue] = set()
        if self._enabled:
            logger.info("Alertes actives : %d regle(s) sur %d topic(s) (%s)",
                        sum(len(r) for r in self._rules.values()),
                        len(self._rules), config.source)

    # --- Observateur du bus -------------------------------------------------

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Evalue la mesure portee par le record.

        Un record rejoue (replay=True : prechauffage, ou retard anterieur au
        demarrage du service) met l'etat a jour sans produire d'evenement :
        apres un redemarrage, les alertes actives sont reconstruites (debut
        compris, alertes maintenues par l'hysteresis aussi) au lieu d'etre
        declenchees de nouveau. Si elles changent, les abonnes recoivent un
        snapshot a la place des evenements : rien n'est historise, journalise
        ni annonce.

        Ignores : les topics sans regle, les records sans valeur numerique,
        les records deja evalues (meme topic, partition et offset : livraison
        "au moins une fois", prechauffage puis consommateur) et la mesure
        d'une autre partition plus ancienne que la derniere evaluee pour le
        capteur."""
        rules = self._rules.get(topic)
        if not rules:
            return
        measurement = measurement_from_record(topic, record)
        if measurement is None or not self._first_reading(topic, record):
            return
        key = (topic, measurement.node_id)
        tracker = self._sensors.get(key)
        if tracker is None:
            tracker = self._sensors[key] = _SensorTracker()
        partition = record.get("partition")
        if not tracker.in_order(partition, measurement.timestamp_ms):
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

    def _first_reading(self, topic: str, record: dict) -> bool:
        """Vrai a la premiere lecture du record (et la retient) ; faux pour un
        record deja evalue : offset inferieur ou egal au plus haut evalue
        sur sa partition."""
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
        """Historise, journalise et diffuse un evenement aux abonnes."""
        self._recent.appendleft(event)
        alert = event.alert
        logger.log(_LOG_LEVELS[event.kind],
                   "[%s] alerte %s (%s) capteur %s%s : %s %s %s, valeur %s",
                   alert.topic, event.kind, alert.severity, alert.node_id,
                   f" ({alert.location})" if alert.location else "",
                   alert.direction, alert.threshold, alert.unit, alert.value)
        self._send({"type": "event", "event": event.to_dict()})

    def _snapshot(self) -> dict:
        """Message de re-synchronisation : toutes les alertes actives."""
        return {"type": "snapshot", "active": self.active()}

    def _send(self, message: dict) -> None:
        """Depose un message dans la file de chaque abonne. File pleine
        (client trop lent) : ses messages en attente sont remplaces par un
        snapshot, qui re-synchronise ses alertes actives ; jeter un evenement
        les fausserait jusqu'a sa reconnexion."""
        for queue in self._subscribers:
            offer_or_reset(queue, message, self._snapshot)

    # --- Requetes de la couche API ------------------------------------------

    @property
    def enabled(self) -> bool:
        """Faux si le fichier d'alertes est absent (aucune evaluation)."""
        return self._enabled

    def rules(self) -> dict[str, list[dict]]:
        """Regles par topic (forme AlertRule de l'API)."""
        return {topic: [rule.to_dict() for rule in rules]
                for topic, rules in self._rules.items()}

    def active(self) -> list[dict]:
        """Alertes actives : critical d'abord, puis de la plus ancienne a la
        plus recente."""
        alerts = sorted(
            (t.state.alert for t in self._sensors.values()
             if t.state.alert is not None),
            key=lambda a: (-SEVERITY_RANK[a.severity], a.since_ms, a.id))
        return [alert.to_dict() for alert in alerts]

    def recent(self) -> list[dict]:
        """Derniers evenements (au plus RECENT_SIZE), le plus recent d'abord."""
        return [event.to_dict() for event in self._recent]

    def subscribe(self) -> asyncio.Queue:
        """Abonne un client ; sa file commence par le snapshot des alertes
        actives, suivi de chaque evenement."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.CLIENT_QUEUE_SIZE)
        queue.put_nowait(self._snapshot())
        self._subscribers.add(queue)
        logger.info("Client WebSocket abonne aux alertes (%d connecte(s))",
                    len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
