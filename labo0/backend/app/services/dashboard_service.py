"""Observateur du bus : alimente le jumeau numerique et pousse aux clients
/ws/dashboard la vue qu'ils ont choisie (rendue par dashboard_views), plus
les notifications d'alerte. Au demarrage, le jumeau est recharge depuis
l'archive SQLite (history_store)."""

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.data_processing import dashboard_views as views
from app.data_management.data_processing.alert_rules import (
    ESCALATED,
    RAISED,
    AlertEvent,
)
from app.data_management.data_processing.digital_twin import (
    HISTORY_MS,
    RAW_MS,
    DigitalTwin,
    place_from,
)
from app.data_management.data_storage.history_store import HistoryStore
from app.services.alert_service import AlertService

logger = logging.getLogger(__name__)


class DashboardService:
    """Aucun await dans on_record : etat et rendu coherents dans la boucle."""

    # Rendu groupe : au plus un envoi par client et par intervalle
    REFRESH_MS = 1000
    # Une vue perimee peut etre jetee (la suivante la remplace)
    CLIENT_QUEUE_SIZE = 100

    def __init__(self, topics: Iterable[str], alerts: AlertService,
                 clock: Callable[[], int] | None = None,
                 store: HistoryStore | None = None) -> None:
        self._topics = list(topics)
        self._alerts = alerts
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._twin = DigitalTwin()
        # File du client -> parametres de sa vue (None tant qu'il n'a rien choisi)
        self._subscriptions: dict[asyncio.Queue, dict | None] = {}
        self._refresh: asyncio.TimerHandle | None = None
        alerts.add_listener(self._on_alert_event)
        if store is not None:
            self._load_history(store)

    # --- Observateur du bus -------------------------------------------------

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Rejoue ou non, meme traitement : l'historique se reconstruit."""
        if self._twin.ingest(topic, record, self._clock()):
            self._schedule_refresh()

    def _on_alert_event(self, event: AlertEvent) -> None:
        self._schedule_refresh()
        if event.kind not in (RAISED, ESCALATED):
            return
        sensor = self._twin.sensor(event.alert.topic, event.alert.node_id)
        toast = views.toast(event, sensor.place if sensor else None)
        for queue in self._subscriptions:
            offer_dropping_oldest(queue, toast)

    def _schedule_refresh(self) -> None:
        if self._refresh is None and self._subscriptions:
            self._refresh = asyncio.get_running_loop().call_later(
                self.REFRESH_MS / 1000, self._push_all)

    def _push_all(self) -> None:
        self._refresh = None
        for queue, params in self._subscriptions.items():
            if params is not None:
                offer_dropping_oldest(queue, self.render(params))

    # --- Historique archive -------------------------------------------------

    def _load_history(self, store: HistoryStore) -> None:
        """Le dernier record de chaque capteur donne son lieu, son unite et sa
        valeur courante, comme a l'ingestion."""
        now = self._clock()
        data = store.load(now, RAW_MS, HISTORY_MS)
        for entry in data["sensors"]:
            record = entry.pop("record")
            payload = record["value"]
            unit = payload.get("unit")
            entry.update(place=asdict(place_from(payload)),
                         unit=unit if isinstance(unit, str) else "",
                         value=payload["value"], updated_ms=record["timestamp_ms"])
        count = self._twin.restore(data, now)
        logger.info("Historique recharge depuis %s : %d capteur(s)",
                    store.path, count)

    # --- Clients de la couche API -------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.CLIENT_QUEUE_SIZE)
        self._subscriptions[queue] = None
        return queue

    def select(self, queue: asyncio.Queue, params: dict) -> None:
        """Vue du client : rendue et envoyee aussitot, puis a chaque
        rafraichissement."""
        self._subscriptions[queue] = params
        offer_dropping_oldest(queue, self.render(params))

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscriptions.pop(queue, None)

    def render(self, params: dict) -> dict:
        return views.render(self._context(), params)

    def chart_csv(self, params: dict) -> tuple[str, str] | None:
        """(nom de fichier, contenu) ou None si le capteur est inconnu."""
        return views.chart_csv(self._context(), params)

    def _context(self) -> views.Context:
        return views.Context(
            sensors=self._twin.sensors(),
            alerts=self._alerts.active_by_sensor(),
            recent=self._alerts.recent_events(),
            rules={t: self._alerts.rules_for(t) for t in self._topics},
            topics=self._topics,
            alerts_enabled=self._alerts.enabled,
            now_ms=self._clock(),
        )
