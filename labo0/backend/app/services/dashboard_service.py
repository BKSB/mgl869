"""Observateur du bus : alimente le jumeau numerique et pousse aux clients
/ws/dashboard la vue qu'ils ont choisie (rendue par dashboard_views), plus
les notifications d'alerte."""

import asyncio
import time
from collections.abc import Callable, Iterable

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.data_processing import dashboard_views as views
from app.data_management.data_processing.alert_rules import (
    ESCALATED,
    RAISED,
    AlertEvent,
)
from app.data_management.data_processing.digital_twin import DigitalTwin
from app.data_management.records import OffsetTracker
from app.services.alert_service import AlertService


class DashboardService:
    """Aucun await : etat et rendu coherents dans la boucle asyncio."""

    # Rendu groupe : au plus un envoi par client et par intervalle
    REFRESH_MS = 1000
    # Une vue perimee peut etre jetee (la suivante la remplace)
    CLIENT_QUEUE_SIZE = 100

    def __init__(self, topics: Iterable[str], alerts: AlertService,
                 clock: Callable[[], int] | None = None) -> None:
        self._topics = list(topics)
        self._alerts = alerts
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._twin = DigitalTwin()
        self._offsets = OffsetTracker()
        # File du client -> parametres de sa vue (None tant qu'il n'a rien choisi)
        self._subscriptions: dict[asyncio.Queue, dict | None] = {}
        self._refresh: asyncio.TimerHandle | None = None
        alerts.add_listener(self._on_alert_event)

    # --- Observateur du bus -------------------------------------------------

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Rejoue ou non, meme traitement : l'historique se reconstruit."""
        if self._offsets.accept(topic, record) \
                and self._twin.ingest(topic, record, self._clock()):
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
