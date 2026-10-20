import asyncio

import pytest

from app.config import AlertsConfig
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    CRITICAL,
    WARNING,
    AlertRule,
)
from app.data_management.record_bus import RecordBus
from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from tests.conftest import drain, make_measurement

CO2 = "gridd.obs.environmental.co2"
NOW = 1_700_000_000_000


@pytest.fixture
def alerts():
    return AlertService(AlertsConfig(enabled=True, rules={
        CO2: [AlertRule(WARNING, ABOVE, 1000, 50),
              AlertRule(CRITICAL, ABOVE, 1500, 50)]}))


@pytest.fixture
def service(alerts):
    dashboard = DashboardService([CO2, "autre"], alerts, clock=lambda: NOW)
    dashboard.REFRESH_MS = 10
    return dashboard


class Emitter:
    def __init__(self, service: DashboardService, alerts: AlertService):
        self.service, self.alerts, self.offset = service, alerts, 0

    async def __call__(self, valeur, ts=NOW, node_id="n1", replay=False,
                       offset=None, **kwargs):
        if offset is None:
            self.offset += 1
            offset = self.offset
        record = make_measurement(valeur, timestamp_ms=ts, offset=offset,
                                  node_id=node_id, topic=CO2, **kwargs)
        await self.service.on_record(CO2, record, replay=replay)
        await self.alerts.on_record(CO2, record, replay=replay)
        return record


@pytest.fixture
def emit(service, alerts):
    return Emitter(service, alerts)


async def settle(service: DashboardService) -> None:
    await asyncio.sleep(service.REFRESH_MS / 1000 * 3)


class TestViews:
    async def test_select_sends_the_view_at_once(self, service, emit):
        await emit(400)
        queue = service.subscribe()

        service.select(queue, {"view": "metric", "metric": "co2"})

        (view,) = drain(queue)
        assert (view["type"], view["view"]) == ("view", "metric")
        assert [s["value_text"] for s in view["metric"]["sensors"]] == ["400"]

    async def test_render_without_subscription(self, service, emit):
        await emit(400, ts=NOW - 10)
        view = service.render({"view": "rooms", "range": "15m"})
        assert view["room"]["sensors"][0]["points"] == [[NOW - 10, 400.0]]
        assert view["room"]["range"] == "15m"

    async def test_refresh_after_records_grouped(self, service, emit):
        queue = service.subscribe()
        service.select(queue, {"view": "rooms"})
        drain(queue)

        await emit(400, ts=NOW - 2)
        await emit(410, ts=NOW - 1)
        await emit(420, ts=NOW)
        await settle(service)

        (view,) = drain(queue)
        assert view["room"]["sensors"][0]["value_text"] == "420"

    async def test_replayed_records_build_history_too(self, service, emit):
        await emit(400, ts=NOW - 1, replay=True)
        await emit(410, ts=NOW, replay=True)
        view = service.render({"view": "rooms"})
        assert view["room"]["sensors"][0]["points"] == \
            [[NOW - 1, 400.0], [NOW, 410.0]]

    async def test_duplicate_record_ignored(self, service, emit):
        await emit(400, ts=NOW - 1, offset=7)
        await emit(999, ts=NOW, offset=7)  # relecture Kafka
        assert service.render({"view": "rooms"})["room"]["sensors"][0][
            "points"] == [[NOW - 1, 400.0]]

    async def test_non_measurement_does_not_refresh(self, service, emit):
        queue = service.subscribe()
        service.select(queue, {"view": "rooms"})
        drain(queue)

        await emit("texte")
        await settle(service)

        assert drain(queue) == []

    async def test_subscriber_without_view_gets_no_view(self, service, emit):
        queue = service.subscribe()
        await emit(400)
        await settle(service)
        assert drain(queue) == []

    async def test_each_subscriber_gets_its_own_view(self, service, emit):
        q1, q2 = service.subscribe(), service.subscribe()
        service.select(q1, {"view": "rooms"})
        service.select(q2, {"view": "alerts"})
        drain(q1), drain(q2)

        await emit(400)
        await settle(service)

        assert [v["view"] for v in drain(q1)] == ["rooms"]
        assert [v["view"] for v in drain(q2)] == ["alerts"]

    async def test_unsubscribe(self, service, emit):
        queue = service.subscribe()
        service.select(queue, {"view": "rooms"})
        drain(queue)
        service.unsubscribe(queue)
        service.unsubscribe(queue)  # sans erreur

        await emit(400)
        await settle(service)

        assert drain(queue) == []

    async def test_subscribed_to_bus(self, service, alerts):
        bus = RecordBus()
        bus.subscribe(service)
        await bus.publish(CO2, make_measurement(400, timestamp_ms=NOW), replay=True)
        assert service.render({})["room"]["sensors"][0]["value_text"] == "400"


class TestAlertNotifications:
    async def test_toast_on_raised_and_escalated_only(self, service, emit):
        viewer, listener = service.subscribe(), service.subscribe()
        service.select(viewer, {"view": "alerts"})
        drain(viewer)

        for valeur in (1120, 1600, 1440, 900):
            await emit(valeur)
        await settle(service)

        toasts = [m for m in drain(viewer) if m["type"] == "toast"]
        assert [t["severity"] for t in toasts] == ["warning", "critical"]
        assert toasts[0]["title"] == "CO₂ · Zone A"
        assert toasts[0]["room_id"] == "z1"
        # Sans vue choisie, un client recoit tout de meme les notifications
        assert [m["type"] for m in drain(listener)] == ["toast", "toast"]

    async def test_view_refreshed_on_acknowledge(self, service, emit, alerts):
        await emit(1120)
        queue = service.subscribe()
        service.select(queue, {"view": "alerts", "filter": "acknowledged"})
        drain(queue)

        alerts.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=NOW)
        await settle(service)

        (view,) = drain(queue)
        assert view["alerts"][0]["state_label"] == "Acquittée · K. Brou"
        assert view["alerts_active"] == 0

    async def test_toast_before_the_refreshed_view(self, service, emit):
        queue = service.subscribe()
        service.select(queue, {"view": "rooms"})
        drain(queue)

        await emit(1120)
        await settle(service)

        assert [m["type"] for m in drain(queue)] == ["toast", "view"]
