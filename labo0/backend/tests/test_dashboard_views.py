"""Vues construites sur un vrai jumeau et un vrai service d'alertes."""

import pytest

from app.config import AlertsConfig
from app.data_management.data_processing import dashboard_views as views
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    RAISED,
    WARNING,
    AlertEvent,
    AlertRule,
)
from app.data_management.data_processing.digital_twin import (
    NO_PLACE_ID,
    DigitalTwin,
    Place,
)
from app.data_management.data_processing.formatting import NARROW_NBSP as F
from app.data_management.data_processing.formatting import NBSP as G
from app.services.alert_service import AlertService

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"
TOPICS = [CO2, TEMPERATURE]
NOW = 1_700_000_000_000
HOUR = 3_600_000


def alerts_config() -> AlertsConfig:
    return AlertsConfig(enabled=True, rules={
        CO2: [AlertRule(WARNING, ABOVE, 1000, 50),
              AlertRule(CRITICAL, ABOVE, 1500, 50)],
        TEMPERATURE: [AlertRule(WARNING, BELOW, 18, 0.5),
                      AlertRule(WARNING, ABOVE, 26, 0.5),
                      AlertRule(CRITICAL, ABOVE, 28, 0.5)],
    })


def measurement(topic, node, valeur, ts, *, offset, room="Salle A",
                floor="É1", building="Local A", unit="ppm") -> dict:
    return {
        "topic": topic, "partition": 0, "offset": offset, "timestamp_ms": ts,
        "key": None,
        "value": {"node_id": node, "type": "mesure", "value": valeur,
                  "unit": unit, "metadata": {
                      "zone": {"id": room.lower().replace(" ", "-"),
                               "label": room},
                      "storey": {"label": floor},
                      "building": {"label": building}}},
    }


class World:
    def __init__(self):
        self.twin = DigitalTwin()
        self.alerts = AlertService(alerts_config())
        self.offset = 0

    async def measure(self, topic, node, valeur, ts=NOW, *, twin=True, **kwargs):
        self.offset += 1
        record = measurement(topic, node, valeur, ts, offset=self.offset, **kwargs)
        if twin:
            self.twin.ingest(topic, record, NOW)
        await self.alerts.on_record(topic, record, replay=False)
        return record

    def context(self, now_ms=NOW) -> views.Context:
        return views.Context(
            sensors=self.twin.sensors(),
            alerts=self.alerts.active_by_sensor(),
            recent=self.alerts.recent_events(),
            rules={t: self.alerts.rules_for(t) for t in TOPICS},
            topics=TOPICS,
            alerts_enabled=True,
            now_ms=now_ms,
        )

    def render(self, **params) -> dict:
        return views.render(self.context(), params)


@pytest.fixture
def world():
    return World()


@pytest.fixture
async def office(world):
    """Deux pieces : Salle A (CO2 en warning, temperature normale) a l'etage 1,
    Bureau (CO2 normal) a l'etage 2 ; une alerte deja resolue sur Bureau."""
    await world.measure(CO2, "co2-a", 950, NOW - HOUR)
    await world.measure(CO2, "co2-a", 1240)
    await world.measure(TEMPERATURE, "temp-a", 21.04, unit="°C")
    await world.measure(CO2, "co2-b", 1600, NOW - 2 * HOUR, room="Bureau",
                        floor="É2")
    await world.measure(CO2, "co2-b", 420, NOW - HOUR, room="Bureau", floor="É2")
    return world


class TestEnvelope:
    def test_header(self, office):
        view = office.render()
        assert view["type"] == "view"
        assert view["site"] == "Local A"
        assert view["alerts_enabled"] is True
        assert view["alerts_active"] == 1
        assert [r["id"] for r in view["ranges"]] == ["15m", "1h", "24h"]
        assert view["view"] == "rooms"

    def test_unknown_view_falls_back_to_rooms(self, office):
        assert office.render(view="inconnue")["view"] == "rooms"
        assert office.render(view=3)["view"] == "rooms"

    async def test_several_buildings_sorted(self, world):
        await world.measure(CO2, "a", 1, building="Pavillon B")
        await world.measure(CO2, "b", 1, building="Pavillon A")
        await world.measure(CO2, "c", 1, building="")
        assert world.render()["site"] == "Pavillon A, Pavillon B"

    async def test_acknowledged_alerts_leave_the_badge(self, office):
        office.alerts.acknowledge(f"{CO2}|co2-a", "K. Brou", at_ms=NOW)
        assert office.render()["alerts_active"] == 0


class TestRoomsView:
    def test_rooms_sorted_by_floor_then_name_with_status(self, office):
        view = office.render(view="rooms")
        assert view["rooms"] == [
            {"id": "salle-a", "name": "Salle A", "floor": "É1",
             "status": "warning"},
            {"id": "bureau", "name": "Bureau", "floor": "É2", "status": "normal"},
        ]

    def test_first_room_selected_by_default(self, office):
        room = office.render(view="rooms")["room"]
        assert room["id"] == "salle-a"
        assert room["building"] == "Local A"
        assert room["status_label"] == "Warning · 1 capteur"
        assert room["summary"] == "2 capteurs"
        assert room["last_ms"] == NOW
        assert room["range"] == "1h"
        # Tuiles dans l'ordre des topics
        assert [s["label"] for s in room["sensors"]] == ["CO₂", "Température"]

    def test_room_selected_by_id(self, office):
        room = office.render(view="rooms", room="bureau")["room"]
        assert room["name"] == "Bureau"
        assert room["status_label"] == "Normal"

    def test_unknown_room(self, office):
        view = office.render(view="rooms", room="inconnue")
        assert view["room"] is None
        assert len(view["rooms"]) == 2

    def test_tile(self, office):
        co2, temperature = office.render(view="rooms")["room"]["sensors"]
        assert co2 == {
            "id": "co2-a", "metric": "co2", "label": "CO₂", "unit": "ppm",
            "room": {"id": "salle-a", "name": "Salle A", "floor": "É1"},
            "value_text": f"1{G}240",
            "status": "warning", "status_label": "Warning",
            "updated_ms": NOW,
            "thresholds": [
                {"severity": "warning", "value": 1000.0,
                 "text": f"W > 1{G}000{F}ppm", "short": f"W > 1{G}000"},
                {"severity": "critical", "value": 1500.0,
                 "text": f"E > 1{G}500{F}ppm", "short": f"E > 1{G}500"},
            ],
            "points": [[NOW - HOUR, 950.0], [NOW, 1240.0]],
            "stats_text": f"1 h : min 950 · max 1{G}240",
        }
        assert temperature["value_text"] == "21,0"
        assert temperature["status"] == "normal"
        assert [t["text"] for t in temperature["thresholds"]] == \
            [f"W < 18{F}°C", f"W > 26{F}°C", f"E > 28{F}°C"]
        assert [t["short"] for t in temperature["thresholds"]] == \
            ["W < 18", "W > 26", "E > 28"]

    def test_range_window(self, office):
        tile = office.render(view="rooms", range="15m")["room"]["sensors"][0]
        assert tile["points"] == [[NOW, 1240.0]]
        assert tile["stats_text"] == f"15 min : min 1{G}240 · max 1{G}240"
        tile = office.render(view="rooms", range="24h")["room"]["sensors"][0]
        assert len(tile["points"]) == 2

    def test_invalid_range_is_default(self, office):
        assert office.render(view="rooms", range="7j")["room"]["range"] == "1h"

    async def test_sensor_silent_on_the_range(self, world):
        await world.measure(CO2, "a", 500, NOW - 2 * HOUR)
        tile = world.render(view="rooms")["room"]["sensors"][0]
        assert (tile["points"], tile["stats_text"]) == ([], "")
        assert tile["value_text"] == "500"

    async def test_latest_metadata_names_the_room(self, world):
        await world.measure(CO2, "a", 1, NOW - 10, room="Ancien nom")
        await world.measure(CO2, "b", 1, NOW, room="Ancien nom")
        # Meme id de zone (ancien-nom), nouveau libelle sur la mesure recente
        record = await world.measure(CO2, "a", 1, NOW + 1, room="Ancien nom")
        record["value"]["metadata"]["zone"]["label"] = "Nouveau nom"
        world.twin.ingest(CO2, record, NOW)
        assert [r["name"] for r in world.render()["rooms"]] == ["Nouveau nom"]

    def test_no_sensor(self, world):
        assert world.render(view="rooms") == {
            **world.render(view="rooms"), "rooms": [], "room": None}

    async def test_room_status_is_the_worst(self, world):
        await world.measure(CO2, "a", 1600)
        await world.measure(CO2, "b", 1200)
        await world.measure(CO2, "c", 400)
        room = world.render(view="rooms")["room"]
        assert (room["status"], room["status_label"]) == \
            ("critical", "Erreur · 2 capteurs")

    async def test_sensor_without_place(self, world):
        record = await world.measure(CO2, "a", 1, twin=False)
        del record["value"]["metadata"]
        world.twin.ingest(CO2, record, NOW)
        assert world.render(view="rooms")["rooms"] == [
            {"id": NO_PLACE_ID, "name": "Sans pièce", "floor": "",
             "status": "normal"}]


class TestMetricView:
    def test_tabs_and_default_metric(self, office):
        view = office.render(view="metric")
        assert view["metrics"] == [{"id": "co2", "label": "CO₂"},
                                   {"id": "temperature", "label": "Température"}]
        metric = view["metric"]
        assert (metric["id"], metric["label"], metric["unit"]) == \
            ("co2", "CO₂", "ppm")
        assert [t["text"] for t in metric["thresholds"]] == \
            [f"W > 1{G}000{F}ppm", f"E > 1{G}500{F}ppm"]
        assert metric["summary"] == "2 capteurs"
        assert metric["counts"] == [
            {"status": "normal", "text": "1 normal"},
            {"status": "warning", "text": "1 warning"},
            {"status": "critical", "text": "0 erreur"},
        ]
        assert (metric["range"], metric["sort"]) == ("1h", "severity")
        assert [s["id"] for s in metric["sorts"]] == ["severity", "room", "value"]

    def test_selected_metric(self, office):
        metric = office.render(view="metric", metric="temperature")["metric"]
        assert metric["unit"] == "°C"
        assert [s["id"] for s in metric["sensors"]] == ["temp-a"]
        assert metric["sensors"][0]["room"]["name"] == "Salle A"

    def test_unknown_metric_is_the_first(self, office):
        assert office.render(view="metric", metric="x")["metric"]["id"] == "co2"

    def test_sort_by_severity_then_room(self, office):
        sensors = office.render(view="metric", sort="severity")["metric"]["sensors"]
        assert [s["id"] for s in sensors] == ["co2-a", "co2-b"]

    def test_sort_by_room(self, office):
        sensors = office.render(view="metric", sort="room")["metric"]["sensors"]
        assert [s["room"]["name"] for s in sensors] == ["Salle A", "Bureau"]

    async def test_sort_by_value_descending(self, office):
        await office.measure(CO2, "co2-c", 800, room="Cuisine")
        sensors = office.render(view="metric", sort="value")["metric"]["sensors"]
        assert [s["value_text"] for s in sensors] == [f"1{G}240", "800", "420"]

    def test_invalid_sort_is_default(self, office):
        assert office.render(view="metric", sort="x")["metric"]["sort"] == \
            "severity"

    def test_metric_without_sensor(self, world):
        metric = world.render(view="metric", metric="temperature")["metric"]
        assert (metric["unit"], metric["sensors"], metric["summary"]) == \
            ("", [], "0 capteur")
        assert metric["thresholds"][0]["text"] == "W < 18"

    def test_no_topic(self, world):
        ctx = views.Context([], {}, [], {}, [], False, NOW)
        assert views.render(ctx, {"view": "metric"})["metric"] is None


class TestAlertsView:
    def test_rows(self, office):
        view = office.render(view="alerts", filter="all")
        active, resolved = view["alerts"]
        assert active == {
            "id": f"{CO2}|co2-a", "key": f"{CO2}|co2-a|{NOW}",
            "severity": "warning", "severity_label": "Warning",
            "room": {"id": "salle-a", "name": "Salle A", "floor": "É1"},
            "metric_label": "CO₂", "sensor_id": "co2-a",
            "value_text": f"1{G}240{F}ppm",
            "threshold_text": f"W > 1{G}000{F}ppm",
            "since_ms": NOW,
            "state": "active", "state_label": "Active", "state_ms": None,
            "can_ack": True,
        }
        assert (resolved["state"], resolved["state_label"]) == \
            ("resolved", "Résolue")
        assert (resolved["since_ms"], resolved["state_ms"]) == \
            (NOW - 2 * HOUR, NOW - HOUR)
        assert resolved["severity_label"] == "Erreur"
        assert resolved["threshold_text"] == f"E > 1{G}500{F}ppm"
        assert resolved["value_text"] == "420 ppm".replace(" ", F)
        assert resolved["can_ack"] is False

    def test_filters_and_summary(self, office):
        view = office.render(view="alerts")
        assert view["filter"] == "active"
        assert view["filters"] == [
            {"id": "active", "label": "Actives", "count": 1},
            {"id": "acknowledged", "label": "Acquittées", "count": 0},
            {"id": "resolved", "label": "Résolues", "count": 1},
            {"id": "all", "label": "Toutes", "count": None},
        ]
        assert view["summary"] == "1 active · 0 erreur, 1 warning"
        assert [a["state"] for a in view["alerts"]] == ["active"]
        assert [a["state"] for a in office.render(view="alerts",
                                                  filter="resolved")["alerts"]] \
            == ["resolved"]
        assert office.render(view="alerts", filter="x")["filter"] == "active"

    async def test_acknowledged(self, office):
        office.alerts.acknowledge(f"{CO2}|co2-a", "K. Brou", at_ms=NOW + 5)
        view = office.render(view="alerts", filter="acknowledged")
        (row,) = view["alerts"]
        assert (row["state_label"], row["state_ms"], row["can_ack"]) == \
            ("Acquittée · K. Brou", NOW + 5, False)
        assert view["summary"] == "0 active · 0 erreur, 0 warning"

    async def test_acknowledged_without_name(self, office):
        office.alerts.acknowledge(f"{CO2}|co2-a", "", at_ms=NOW + 5)
        (row,) = office.render(view="alerts", filter="acknowledged")["alerts"]
        assert row["state_label"] == "Acquittée"

    async def test_order_active_acknowledged_resolved_newest_first(self, world):
        await world.measure(CO2, "old", 1200, NOW - 3)
        await world.measure(CO2, "new", 1600, NOW - 2)
        await world.measure(CO2, "ack", 1200, NOW - 1)
        world.alerts.acknowledge(f"{CO2}|ack", "K", at_ms=NOW)
        await world.measure(CO2, "r1", 1200, NOW - 10)
        await world.measure(CO2, "r1", 900, NOW - 9)
        await world.measure(CO2, "r2", 1200, NOW - 8)
        await world.measure(CO2, "r2", 900, NOW - 7)

        view = world.render(view="alerts", filter="all")
        assert [a["sensor_id"] for a in view["alerts"]] == \
            ["new", "old", "ack", "r2", "r1"]
        assert view["summary"] == "2 actives · 1 erreur, 1 warning"

    async def test_room_from_alert_location_when_unknown_to_twin(self, world):
        await world.measure(CO2, "x", 1200, twin=False, room="Labo")
        (row,) = world.render(view="alerts")["alerts"]
        assert row["room"] == {"id": NO_PLACE_ID, "name": "Labo", "floor": ""}


class TestToast:
    async def test_raised(self, office):
        event = next(e for e in office.alerts.recent_events()
                     if e.kind == RAISED and e.alert.node_id == "co2-a")
        toast = views.toast(event, office.twin.sensor(CO2, "co2-a").place)
        assert toast == {
            "type": "toast",
            "id": f"{CO2}|co2-a|{NOW}|raised",
            "severity": "warning", "severity_label": "Warning",
            "at_ms": NOW,
            "title": "CO₂ · Salle A",
            "value_text": f"1{G}240{F}ppm",
            "text": f"> seuil warning 1{G}000{F}ppm",
            "alert_id": f"{CO2}|co2-a",
            "room_id": "salle-a",
        }

    async def test_place_fallback(self, office):
        event = next(e for e in office.alerts.recent_events()
                     if e.kind == RAISED and e.alert.node_id == "co2-a")
        toast = views.toast(event, None)
        assert toast["room_id"] == NO_PLACE_ID
        assert toast["title"] == "CO₂ · Salle A"  # location de l'alerte

    async def test_unknown_place(self, world):
        record = await world.measure(CO2, "x", 1700)
        event = AlertEvent(RAISED, NOW, world.alerts.active_by_sensor()[(CO2, "x")])
        del record["value"]["metadata"]
        toast = views.toast(event, Place(NO_PLACE_ID, "Sans pièce"))
        assert toast["text"] == f"> seuil erreur 1{G}500{F}ppm"
        assert toast["title"] == "CO₂ · Sans pièce"


class TestDownsample:
    async def test_bounded_points_keep_first_and_last(self, world):
        for i in range(600):
            await world.measure(CO2, "a", i, NOW - 600 + i)
        points = world.render(view="rooms")["room"]["sensors"][0]["points"]
        assert len(points) == views.MAX_POINTS
        assert points[0] == [NOW - 600, 0.0]
        assert points[-1] == [NOW - 1, 599.0]
        assert points == sorted(points)
