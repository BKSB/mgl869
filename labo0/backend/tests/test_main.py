import logging

import pytest
import yaml

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
from app.services.dashboard_service import DashboardService
from tests.conftest import make_measurement, make_record


@pytest.fixture
def created_buses(monkeypatch):
    """RecordBus construits par app.main (create_bus) ; seul le nom importe
    dans app.main est remplace."""
    crees = []

    class SpyBus(RecordBus):
        def __init__(self) -> None:
            super().__init__()
            crees.append(self)

    monkeypatch.setattr(main_module, "RecordBus", SpyBus)
    return crees


@pytest.fixture
def run_main(monkeypatch, plaintext_settings, created_buses):
    """main() sans YAML ni serveur ; retourne (code, applications servies)."""
    applications = []

    def _run(**settings_overrides):
        monkeypatch.setattr(main_module, "Settings",
                            lambda: plaintext_settings(**settings_overrides))
        monkeypatch.setattr(main_module.uvicorn, "run",
                            lambda app, **kwargs: applications.append(app))
        return main_module.main(), applications
    return _run


async def test_hub_subscribed_to_service_bus(run_main, created_buses):
    code, applications = run_main()

    assert code == 0
    service = applications[0].state.streaming
    # Un seul bus, construit par create_bus
    (bus,) = created_buses
    hub, _dashboard, _alerts = bus.observers
    assert isinstance(hub, TopicHub)

    # Le hub inscrit sur le bus est bien celui qui sert les clients WebSocket
    queue = service.subscribe("topic.a")
    await bus.publish("topic.a", make_record())
    assert queue.qsize() == 1


async def test_alerts_subscribed_after_hub(run_main, created_buses):
    alerts_config = AlertsConfig(enabled=True, rules={
        "topic.a": [AlertRule(WARNING, ABOVE, 1000)]})
    code, applications = run_main(alerts=alerts_config)

    assert code == 0
    app = applications[0]
    (bus,) = created_buses
    hub, dashboard, alerts = bus.observers
    # Ordre d'inscription : le hub d'abord (flux temps reel), le dashboard
    # (piece connue avant les notifications), puis les alertes
    assert isinstance(hub, TopicHub)
    assert isinstance(dashboard, DashboardService)
    assert isinstance(alerts, AlertService)
    # Les services inscrits sont ceux de l'API, avec les regles de la config
    assert app.state.alerts is alerts
    assert app.state.dashboard is dashboard
    assert alerts.enabled
    assert list(alerts.rules()) == ["topic.a"]

    await bus.publish("topic.a", make_measurement(1120, topic="topic.a"))
    assert [a["topic"] for a in alerts.active()] == ["topic.a"]
    # Le dashboard connait les topics configures (onglets Par capteur)
    assert [m["id"] for m in dashboard.render({"view": "metric"})["metrics"]] \
        == ["a", "b"]


def test_service_starts_with_alerts_disabled(run_main):
    code, applications = run_main()

    assert code == 0
    assert not applications[0].state.alerts.enabled


def test_invalid_alerts_config_no_server(run_main, caplog):
    alerts_config = AlertsConfig(enabled=True, source="alerts.yaml", rules={
        "topic.inconnu": [AlertRule(WARNING, ABOVE, 1)]})
    with caplog.at_level(logging.ERROR):
        code, applications = run_main(alerts=alerts_config)

    assert code == 1
    assert applications == []
    assert "topic non consomme" in caplog.text
    assert "topic.inconnu" in caplog.text


def test_invalid_config_no_server(run_main, caplog):
    with caplog.at_level(logging.ERROR):
        code, applications = run_main(topic_configs=[])

    assert code == 1
    assert applications == []
    assert "Aucun topic" in caplog.text


@pytest.mark.parametrize("erreur", [
    FileNotFoundError("Fichier de topics introuvable : config/topics.yaml"),
    ValueError("config/topics.yaml : contenu invalide (...)"),
    yaml.YAMLError("cle dupliquee : 'a'"),
])
def test_invalid_topics_yaml_message_without_traceback(monkeypatch, caplog,
                                                       erreur):
    def failing_settings():
        raise erreur

    monkeypatch.setattr(main_module, "Settings", failing_settings)
    monkeypatch.setattr(main_module.uvicorn, "run",
                        lambda app, **kwargs: pytest.fail("serveur lance"))
    with caplog.at_level(logging.ERROR):
        assert main_module.main() == 1

    assert f"Configuration invalide : {erreur}" in caplog.text
