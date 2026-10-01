"""Composition root : construit la configuration, le hub, le service et
l'application FastAPI, puis lance le serveur. Toute la logique vit dans
la couche service (app/services) ; les routes dans la couche API (app/api)."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.services.streaming_service import StreamingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(service: StreamingService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.start()
        watchdog = asyncio.create_task(service.watch_consumers())
        yield
        watchdog.cancel()
        await service.stop()

    app = FastAPI(title="gridd-kafka-consumer", lifespan=lifespan)
    app.state.streaming = service
    app.include_router(router)
    return app


def main() -> int:
    settings = Settings()
    hub = TopicHub(
        history_per_sensor={t.name: t.history_per_sensor
                            for t in settings.topic_configs},
    )
    service = StreamingService(settings, hub)

    errors = service.validate()
    if errors:
        for error in errors:
            logger.error(error)
        return 1

    uvicorn.run(create_app(service), host="0.0.0.0", port=8000, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
