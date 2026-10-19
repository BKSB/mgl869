"""Tests du composition root (app.main) : assemblage du hub, du service
d'alertes, du bus de records et du service, sans lancer de serveur."""

import logging

import pytest

from app import main as main_module
from app.config import AlertsConfig
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    WARNING,
    AlertRule,
)
from app.data_management.record_bus import RecordBus
from app.services.alert_service import AlertService
from tests.conftest import make_mesure, make_record


@pytest.fixture
def bus_crees(monkeypatch):
    """Espionne les RecordBus construits par app.main (create_bus) : seul le
    nom importe dans app.main est remplace."""
    crees = []

    class BusEspion(RecordBus):
        def __init__(self) -> None:
            super().__init__()
            crees.append(self)

    monkeypatch.setattr(main_module, "RecordBus", BusEspion)
    return crees


@pytest.fixture
def lancer(monkeypatch, plaintext_settings, bus_crees):
    """Remplace Settings (sans YAML ni SSL) et uvicorn.run (aucun serveur
    lance) ; retourne les applications qui auraient ete servies."""
    applications = []

    def _lancer(**settings_overrides):
        monkeypatch.setattr(main_module, "Settings",
                            lambda: plaintext_settings(**settings_overrides))
        monkeypatch.setattr(main_module.uvicorn, "run",
                            lambda app, **kwargs: applications.append(app))
        return main_module.main(), applications
    return _lancer


async def test_hub_inscrit_sur_le_bus_du_service(lancer, bus_crees):
    code, applications = lancer()

    assert code == 0
    service = applications[0].state.streaming
    # Composition explicite : un seul bus, construit par create_bus, celui ou
    # s'inscriront les futurs observateurs
    (bus,) = bus_crees
    hub, _alerts = bus.observers
    assert isinstance(hub, TopicHub)

    # Le hub inscrit sur le bus est bien celui qui sert les clients WebSocket
    queue = service.subscribe("topic.a")
    await bus.publish("topic.a", make_record())
    assert queue.qsize() == 1


async def test_alertes_inscrites_sur_le_bus_apres_le_hub(lancer, bus_crees):
    alerts_config = AlertsConfig(enabled=True, rules={
        "topic.a": [AlertRule(WARNING, ABOVE, 1000)]})
    code, applications = lancer(alerts=alerts_config)

    assert code == 0
    app = applications[0]
    (bus,) = bus_crees
    hub, alerts = bus.observers
    # Ordre d'inscription : le hub d'abord (flux temps reel), puis les alertes
    assert isinstance(hub, TopicHub)
    assert isinstance(alerts, AlertService)
    # Le service inscrit est celui expose a la couche API, construit avec
    # les regles de la configuration
    assert app.state.alerts is alerts
    assert alerts.enabled
    assert list(alerts.rules()) == ["topic.a"]

    await bus.publish("topic.a", make_mesure(1120, topic="topic.a"))
    assert [a["topic"] for a in alerts.active()] == ["topic.a"]


def test_alertes_desactivees_le_service_demarre(lancer):
    code, applications = lancer()

    assert code == 0
    assert not applications[0].state.alerts.enabled


def test_configuration_d_alertes_invalide_pas_de_serveur(lancer, caplog):
    alerts_config = AlertsConfig(enabled=True, source="alerts.yaml", rules={
        "topic.inconnu": [AlertRule(WARNING, ABOVE, 1)]})
    with caplog.at_level(logging.ERROR):
        code, applications = lancer(alerts=alerts_config)

    assert code == 1
    assert applications == []
    assert "topic non consomme" in caplog.text
    assert "topic.inconnu" in caplog.text


def test_configuration_invalide_pas_de_serveur(lancer, caplog):
    with caplog.at_level(logging.ERROR):
        code, applications = lancer(topic_configs=[])

    assert code == 1
    assert applications == []
    assert "Aucun topic" in caplog.text
