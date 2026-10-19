"""Tests de la couche API (HTTP + WebSocket) via le TestClient FastAPI,
avec un vrai StreamingService dont les taches Kafka sont simulees et un
vrai AlertService, assembles comme dans main() (create_bus)."""

import asyncio
from functools import partial

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import AlertsConfig
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    CRITICAL,
    WARNING,
    AlertRule,
)
from app.main import create_app, create_bus
from app.services import streaming_service
from app.services.alert_service import AlertService
from app.services.streaming_service import StreamingService
from tests.conftest import make_mesure, make_record


@pytest.fixture
def hub():
    return TopicHub()


@pytest.fixture
def alerts():
    return AlertService(AlertsConfig(enabled=True, rules={
        "topic.a": [AlertRule(WARNING, ABOVE, 1000, 50),
                    AlertRule(CRITICAL, ABOVE, 1500, 50)],
    }))


@pytest.fixture
def make_client(monkeypatch, plaintext_settings, hub):
    async def fake_consume(**kwargs):
        await asyncio.Event().wait()

    async def fake_warmup(**kwargs):
        pass

    monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
    monkeypatch.setattr(streaming_service, "warmup_topic", fake_warmup)

    def _make(alert_service: AlertService) -> TestClient:
        # Meme assemblage que main() : le bus notifie le hub puis les alertes
        bus = create_bus(hub, alert_service)
        service = StreamingService(plaintext_settings(), hub, bus)
        test_client = TestClient(create_app(service, alert_service))
        test_client.bus = bus  # point de publication des mesures de test
        return test_client
    return _make


@pytest.fixture
def client(make_client, alerts):
    with make_client(alerts) as test_client:
        yield test_client


def publier_mesure(client: TestClient, valeur, ts, offset) -> None:
    """Publie une mesure temps reel sur le bus de l'application DANS la
    boucle du serveur (comme le consommateur), pour que les abonnes
    WebSocket soient reveilles."""
    record = make_mesure(valeur, timestamp_ms=ts, offset=offset,
                         topic="topic.a")
    client.portal.call(partial(client.bus.publish, "topic.a", record))


def attendre_desabonnement(client: TestClient, abonnes: set) -> None:
    """La deconnexion est traitee de facon asynchrone par le serveur : des
    requetes HTTP suivantes laissent au handler le temps de finir."""
    for _ in range(50):
        client.get("/health")
        if not abonnes:
            break


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
    # Identite du capteur fournie par le backend (records.sensor_id)
    assert [first["sensor_id"], second["sensor_id"]] == ["n2", "n1"]


class TestAlertes:
    def test_get_alertes(self, client):
        publier_mesure(client, 1120, ts=100, offset=1)

        response = client.get("/api/alerts")

        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        (alerte,) = body["active"]
        assert alerte["id"] == "topic.a|n1"
        assert alerte["severity"] == "warning"
        assert [e["kind"] for e in body["recent"]] == ["raised"]
        assert body["recent"][0]["alert"] == alerte
        assert body["rules"] == {"topic.a": [
            {"severity": "warning", "direction": "above",
             "threshold": 1000.0, "hysteresis": 50.0},
            {"severity": "critical", "direction": "above",
             "threshold": 1500.0, "hysteresis": 50.0},
        ]}

    def test_get_alertes_desactivees(self, make_client):
        with make_client(AlertService(AlertsConfig())) as client:
            response = client.get("/api/alerts")

        assert response.status_code == 200
        assert response.json() == {"enabled": False, "active": [],
                                   "recent": [], "rules": {}}

    def test_websocket_snapshot_puis_evenements(self, client):
        publier_mesure(client, 1120, ts=100, offset=1)

        # /ws/alerts n'est pas capture par /ws/{topic} (pas de fermeture 4004)
        with client.websocket_connect("/ws/alerts") as ws:
            snapshot = ws.receive_json()
            publier_mesure(client, 1600, ts=200, offset=2)
            escalade = ws.receive_json()
            publier_mesure(client, 900, ts=300, offset=3)
            resolution = ws.receive_json()

        assert snapshot["type"] == "snapshot"
        assert [a["id"] for a in snapshot["active"]] == ["topic.a|n1"]
        assert escalade["type"] == "event"
        assert escalade["event"]["kind"] == "escalated"
        assert escalade["event"]["at_ms"] == 200
        assert escalade["event"]["alert"]["severity"] == "critical"
        assert resolution["event"]["kind"] == "resolved"
        assert resolution["event"]["alert"]["value"] == 900

    def test_websocket_desactive_snapshot_vide_et_reste_ouvert(self,
                                                               make_client):
        alerts = AlertService(AlertsConfig())
        with make_client(alerts) as client:
            with client.websocket_connect("/ws/alerts") as ws:
                assert ws.receive_json() == {"type": "snapshot", "active": []}
                # Connexion toujours ouverte : un message du client (ignore)
                # est accepte et le service compte toujours l'abonne
                ws.send_text("ping")
                client.get("/health")
                assert len(alerts._subscribers) == 1
            attendre_desabonnement(client, alerts._subscribers)

        assert not alerts._subscribers

    def test_websocket_desabonne_a_la_deconnexion(self, client, alerts):
        with client.websocket_connect("/ws/alerts") as ws:
            ws.receive_json()
        attendre_desabonnement(client, alerts._subscribers)
        assert not alerts._subscribers


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
