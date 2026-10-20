"""Couche API : HTTP/WebSocket <-> StreamingService, AlertService et
DashboardService."""

import asyncio
import json
import time
from collections.abc import Callable

from fastapi import APIRouter, Body, HTTPException, Request, Response, WebSocket
from starlette.requests import HTTPConnection

from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from app.services.streaming_service import StreamingService

router = APIRouter()


def _service(connection: HTTPConnection) -> StreamingService:
    return connection.app.state.streaming


def _alerts(connection: HTTPConnection) -> AlertService:
    return connection.app.state.alerts


def _dashboard(connection: HTTPConnection) -> DashboardService:
    return connection.app.state.dashboard


@router.get("/health")
def health(request: Request) -> dict:
    return _service(request).health()


@router.get("/api/topics")
def topics(request: Request) -> dict:
    """Topics consommes et URL du flux WebSocket de chacun."""
    return {"topics": [{"name": t, "websocket": f"/ws/{t}"}
                       for t in _service(request).topics()]}


# Routes async, pas def : l'etat des services est lu dans la boucle asyncio
# qui le modifie, pas dans un thread du pool

@router.get("/api/alerts")
async def alerts(request: Request) -> dict:
    """Alertes actives, evenements recents et regles par topic."""
    service = _alerts(request)
    return {
        "enabled": service.enabled,
        "active": service.active(),
        "recent": service.recent(),
        "rules": service.rules(),
    }


@router.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: Request,
                            body: dict | None = Body(default=None)) -> dict:
    """Corps { "by": "<nom>" } optionnel ; 404 sans alerte active, 409 si elle
    est deja acquittee."""
    by = str((body or {}).get("by") or "").strip()
    try:
        alert = _alerts(request).acknowledge(alert_id, by,
                                             at_ms=int(time.time() * 1000))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"alert": alert}


@router.get("/api/dashboard")
async def dashboard(request: Request) -> dict:
    """Meme vue que /ws/dashboard (parametres en query string, cf.
    dashboard_views), sans abonnement."""
    return _dashboard(request).render(dict(request.query_params))


@router.get("/api/chart.csv")
async def chart_csv(request: Request) -> Response:
    """Cases affichees par le graphe plein ecran (metric, sensor, range, from,
    to), en CSV ; 404 si le capteur est inconnu."""
    result = _dashboard(request).chart_csv(dict(request.query_params))
    if result is None:
        raise HTTPException(status_code=404, detail="capteur inconnu")
    filename, text = result
    return Response(text, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


async def _forward(queue: asyncio.Queue, websocket: WebSocket) -> None:
    while True:
        await websocket.send_json(await queue.get())


async def _pump(websocket: WebSocket, queue: asyncio.Queue,
                unsubscribe: Callable[[], None],
                on_text: Callable[[str], None] | None = None) -> None:
    """Deconnexion detectee en lecture, pas par un envoi en echec : un topic
    muet n'enverrait rien. Messages du client ignores sans `on_text`."""
    sender = asyncio.create_task(_forward(queue, websocket))
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if on_text and message.get("text") is not None:
                on_text(message["text"])
    finally:
        # Desabonnement AVANT tout await : un await peut etre annule a l'arret
        unsubscribe()
        sender.cancel()
        # Recupere l'issue de l'envoyeur : aucune exception orpheline
        await asyncio.gather(sender, return_exceptions=True)


# Declarees AVANT /ws/{topic}, qui capturerait sinon "alerts" ou "dashboard"
# comme un topic

@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket) -> None:
    """Snapshot des alertes actives a la connexion, puis chaque evenement."""
    service = _alerts(websocket)
    await websocket.accept()
    queue = service.subscribe()
    await _pump(websocket, queue, lambda: service.unsubscribe(queue))


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """Le client envoie les parametres de sa vue (JSON, cf. dashboard_views) ;
    il recoit la vue aussitot, puis a chaque changement de donnees, et les
    notifications d'alerte (`toast`)."""
    service = _dashboard(websocket)
    await websocket.accept()
    queue = service.subscribe()

    def select(text: str) -> None:
        try:
            params = json.loads(text)
        except ValueError:
            return
        if isinstance(params, dict):
            service.select(queue, params)

    await _pump(websocket, queue, lambda: service.unsubscribe(queue), select)


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
