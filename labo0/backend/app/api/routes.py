"""Couche API : traduit HTTP/WebSocket <-> appels au StreamingService.
"""

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.services.streaming_service import StreamingService

router = APIRouter()


def _service(scope_holder) -> StreamingService:
    return scope_holder.app.state.streaming


@router.get("/health")
def health(request: Request) -> dict:
    return _service(request).health()


@router.get("/api/topics")
def topics(request: Request) -> dict:
    """Liste des topics consommes et l'URL du flux WebSocket de chacun."""
    return {"topics": [{"name": t, "websocket": f"/ws/{t}"}
                       for t in _service(request).topics()]}


@router.websocket("/ws/{topic}")
async def websocket_topic(websocket: WebSocket, topic: str) -> None:
    """Flux WebSocket dedie a UN topic : historique par capteur a la
    connexion, puis chaque message Kafka en JSON des sa reception."""
    service = _service(websocket)
    await websocket.accept()
    if not service.is_known_topic(topic):
        # Accepter puis fermer : le client recoit le code 4004 et la raison,
        # au lieu d'un refus de handshake HTTP 403 opaque
        await websocket.close(code=4004, reason=f"Topic inconnu : {topic}")
        return
    queue = service.subscribe(topic)
    try:
        while True:
            record = await queue.get()
            await websocket.send_json(record)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(topic, queue)
