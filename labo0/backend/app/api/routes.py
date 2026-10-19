"""Couche API : traduit HTTP/WebSocket <-> appels au StreamingService et
a l'AlertService.
"""

import asyncio

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.services.alert_service import AlertService
from app.services.streaming_service import StreamingService

router = APIRouter()


def _service(scope_holder) -> StreamingService:
    return scope_holder.app.state.streaming


def _alerts(scope_holder) -> AlertService:
    return scope_holder.app.state.alerts


@router.get("/health")
def health(request: Request) -> dict:
    return _service(request).health()


@router.get("/api/topics")
def topics(request: Request) -> dict:
    """Liste des topics consommes et l'URL du flux WebSocket de chacun."""
    return {"topics": [{"name": t, "websocket": f"/ws/{t}"}
                       for t in _service(request).topics()]}


@router.get("/api/alerts")
async def alerts(request: Request) -> dict:
    """Etat des alertes : actives, evenements recents et regles par topic.
    Coroutine (pas `def`) : executee dans la boucle asyncio, comme
    l'AlertService qui y modifie son etat, et non dans un thread."""
    service = _alerts(request)
    return {
        "enabled": service.enabled,
        "active": service.active(),
        "recent": service.recent(),
        "rules": service.rules(),
    }


async def _forward(queue: asyncio.Queue, websocket: WebSocket) -> None:
    """Envoie au client chaque message de sa file."""
    while True:
        await websocket.send_json(await queue.get())


# Declaree AVANT /ws/{topic}, qui capturerait sinon "alerts" comme un topic
@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket) -> None:
    """Flux des alertes : snapshot des alertes actives a la connexion, puis
    chaque evenement (raised, escalated, deescalated, resolved)."""
    service = _alerts(websocket)
    await websocket.accept()
    queue = service.subscribe()
    sender = asyncio.create_task(_forward(queue, websocket))
    try:
        # Les alertes sont rares (voire desactivees) : la deconnexion du
        # client est detectee en lecture, sans attendre un envoi qui echoue.
        # Les messages du client sont ignores.
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        # Desabonnement AVANT tout await : si le handler est annule (arret
        # du serveur), l'await suivant peut etre interrompu a son tour
        service.unsubscribe(queue)
        sender.cancel()
        # Recupere l'issue de l'envoyeur (annulation ou echec d'envoi a un
        # client parti) pour qu'aucune exception ne reste orpheline
        await asyncio.gather(sender, return_exceptions=True)


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
