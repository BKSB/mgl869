"""Couche API : HTTP/WebSocket <-> StreamingService et AlertService."""

import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Request, WebSocket
from starlette.requests import HTTPConnection

from app.services.alert_service import AlertService
from app.services.streaming_service import StreamingService

router = APIRouter()


def _service(connection: HTTPConnection) -> StreamingService:
    return connection.app.state.streaming


def _alerts(connection: HTTPConnection) -> AlertService:
    return connection.app.state.alerts


@router.get("/health")
def health(request: Request) -> dict:
    return _service(request).health()


@router.get("/api/topics")
def topics(request: Request) -> dict:
    """Topics consommes et URL du flux WebSocket de chacun."""
    return {"topics": [{"name": t, "websocket": f"/ws/{t}"}
                       for t in _service(request).topics()]}


@router.get("/api/alerts")
async def alerts(request: Request) -> dict:
    """Alertes actives, evenements recents et regles par topic."""
    # async, pas def : l'etat de l'AlertService est lu dans la boucle asyncio
    # qui le modifie, pas dans un thread du pool
    service = _alerts(request)
    return {
        "enabled": service.enabled,
        "active": service.active(),
        "recent": service.recent(),
        "rules": service.rules(),
    }


async def _forward(queue: asyncio.Queue, websocket: WebSocket) -> None:
    while True:
        await websocket.send_json(await queue.get())


async def _pump(websocket: WebSocket, queue: asyncio.Queue,
                unsubscribe: Callable[[], None]) -> None:
    """Deconnexion detectee en lecture, pas par un envoi en echec : un topic
    muet n'enverrait rien. Messages du client ignores."""
    sender = asyncio.create_task(_forward(queue, websocket))
    try:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        # Desabonnement AVANT tout await : un await peut etre annule a l'arret
        unsubscribe()
        sender.cancel()
        # Recupere l'issue de l'envoyeur : aucune exception orpheline
        await asyncio.gather(sender, return_exceptions=True)


# Declaree AVANT /ws/{topic}, qui capturerait sinon "alerts" comme un topic
@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket) -> None:
    """Snapshot des alertes actives a la connexion, puis chaque evenement."""
    service = _alerts(websocket)
    await websocket.accept()
    queue = service.subscribe()
    await _pump(websocket, queue, lambda: service.unsubscribe(queue))


@router.websocket("/ws/{topic}")
async def websocket_topic(websocket: WebSocket, topic: str) -> None:
    """Historique par capteur, puis chaque record en temps reel."""
    service = _service(websocket)
    await websocket.accept()
    if not service.is_known_topic(topic):
        # Accepter puis fermer : code 4004 et raison, pas un 403 opaque
        await websocket.close(code=4004, reason=f"Topic inconnu : {topic}")
        return
    queue = service.subscribe(topic)
    await _pump(websocket, queue, lambda: service.unsubscribe(topic, queue))
