"""Composition root : assemble les dependances et lance le serveur."""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
import yaml
from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from app.services.streaming_service import StreamingService

logger = logging.getLogger(__name__)


def create_app(service: StreamingService, alerts: AlertService,
               dashboard: DashboardService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.start()
        yield
        await service.stop()

    app = FastAPI(title="gridd-kafka-consumer", lifespan=lifespan)
    app.state.streaming = service
    app.state.alerts = alerts
    app.state.dashboard = dashboard
    app.include_router(router)
    return app


def create_bus(hub: TopicHub, alerts: AlertService,
               dashboard: DashboardService) -> RecordBus:
    """Seul point d'inscription des observateurs, notifies dans cet ordre."""
    bus = RecordBus()
    bus.subscribe(hub)  # 1er : le temps reel n'attend pas les alertes
    bus.subscribe(dashboard)  # avant les alertes : la piece est connue au toast
    bus.subscribe(alerts)
    return bus


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )
    try:
        settings = Settings()
    # topics.yaml absent ou invalide : un message, pas une traceback
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.error("Configuration invalide : %s", exc)
        return 1
    errors = settings.validate()
    if errors:
        for error in errors:
            logger.error(error)
        return 1

    hub = TopicHub(
        history_per_sensor={t.name: t.history_per_sensor
                            for t in settings.topic_configs},
    )
    alerts = AlertService(settings.alerts)
    dashboard = DashboardService(settings.topics, alerts)
    service = StreamingService(settings, hub,
                               create_bus(hub, alerts, dashboard))
    uvicorn.run(create_app(service, alerts, dashboard), host="0.0.0.0",
                port=8000, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
