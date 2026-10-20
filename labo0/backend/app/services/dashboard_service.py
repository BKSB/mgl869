"""Observateur du bus : alimente le jumeau numerique et pousse aux clients
/ws/dashboard la vue qu'ils ont choisie (rendue par dashboard_views), plus
les notifications d'alerte. L'historique du jumeau est sauvegarde sur disque
(instantane JSON) pour survivre aux redemarrages."""

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.data_processing import dashboard_views as views
from app.data_management.data_processing.alert_rules import (
    ESCALATED,
    RAISED,
    AlertEvent,
)
from app.data_management.data_processing.digital_twin import DigitalTwin
from app.services.alert_service import AlertService

logger = logging.getLogger(__name__)


class DashboardService:
    """Aucun await dans on_record : etat et rendu coherents dans la boucle."""

    # Rendu groupe : au plus un envoi par client et par intervalle
    REFRESH_MS = 1000
    # Une vue perimee peut etre jetee (la suivante la remplace)
    CLIENT_QUEUE_SIZE = 100
    SNAPSHOT_INTERVAL_S = 600

    def __init__(self, topics: Iterable[str], alerts: AlertService,
                 clock: Callable[[], int] | None = None,
                 snapshot_path: Path | None = None) -> None:
        self._topics = list(topics)
        self._alerts = alerts
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._twin = DigitalTwin()
        self._snapshot_path = snapshot_path
        self._saver: asyncio.Task | None = None
        # File du client -> parametres de sa vue (None tant qu'il n'a rien choisi)
        self._subscriptions: dict[asyncio.Queue, dict | None] = {}
        self._refresh: asyncio.TimerHandle | None = None
        alerts.add_listener(self._on_alert_event)
        self._load_snapshot()

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

    # --- Instantane de l'historique ----------------------------------------

    def _load_snapshot(self) -> None:
        path = self._snapshot_path
        if path is None or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            count = self._twin.restore(data, self._clock())
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning("Instantane du dashboard illisible (%s) : %s", path, exc)
            return
        logger.info("Instantane du dashboard charge : %d capteur(s) (%s)", count, path)

    async def save_snapshot(self) -> None:
        """Ecriture atomique (fichier temporaire puis renommage) hors de la
        boucle ; un echec est journalise, jamais fatal."""
        path = self._snapshot_path
        if path is None:
            return
        text = json.dumps(self._twin.to_dict(), ensure_ascii=False)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            logger.warning("Instantane du dashboard non sauvegarde (%s) : %s",
                           path, exc)

    async def _autosave(self) -> None:
        while True:
            await asyncio.sleep(self.SNAPSHOT_INTERVAL_S)
            await self.save_snapshot()

    def start(self) -> None:
        if self._snapshot_path is not None and self._saver is None:
            self._saver = asyncio.create_task(self._autosave(),
                                              name="dashboard-snapshot")

    async def stop(self) -> None:
        if self._saver is not None:
            self._saver.cancel()
            await asyncio.gather(self._saver, return_exceptions=True)
            self._saver = None
        await self.save_snapshot()

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
