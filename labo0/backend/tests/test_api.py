"""Tests de la couche API (HTTP + WebSocket) via le TestClient FastAPI,
avec un vrai StreamingService dont les taches Kafka sont simulees."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.data_management.data_distribution.websocket_hub import TopicHub
from app.main import create_app
from app.services import streaming_service
from app.services.streaming_service import StreamingService
from tests.conftest import make_record


@pytest.fixture
def hub():
    return TopicHub()


@pytest.fixture
def client(monkeypatch, plaintext_settings, hub):
    async def fake_consume(**kwargs):
        await asyncio.Event().wait()

    async def fake_warmup(**kwargs):
        pass

    monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
    monkeypatch.setattr(streaming_service, "warmup_topic", fake_warmup)
    service = StreamingService(plaintext_settings(), hub)
    with TestClient(create_app(service)) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "consumers": {"topic.a": True, "topic.b": True},
    }


def test_liste_des_topics(client):
    response = client.get("/api/topics")
    assert response.status_code == 200
    assert response.json() == {"topics": [
        {"name": "topic.a", "websocket": "/ws/topic.a"},
        {"name": "topic.b", "websocket": "/ws/topic.b"},
    ]}


def test_websocket_topic_inconnu_ferme_avec_4004(client):
    with client.websocket_connect("/ws/inconnu") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4004
    assert "inconnu" in exc.value.reason


def test_websocket_rejoue_l_historique(client, hub):
    hub.publish("topic.a", make_record("n1", offset=1, timestamp_ms=200))
    hub.publish("topic.a", make_record("n2", offset=2, timestamp_ms=100))
    hub.publish("topic.b", make_record("n3", offset=3, timestamp_ms=50))

    with client.websocket_connect("/ws/topic.a") as ws:
        first, second = ws.receive_json(), ws.receive_json()

    assert [first["offset"], second["offset"]] == [2, 1]


def test_websocket_desabonne_a_la_deconnexion(client, hub):
    with client.websocket_connect("/ws/topic.a"):
        pass
    # La deconnexion est traitee de facon asynchrone par le serveur :
    # une requete HTTP suivante garantit que le handler a eu le temps de finir
    for _ in range(50):
        client.get("/health")
        if not hub._subscribers.get("topic.a"):
            break
    assert not hub._subscribers.get("topic.a")
