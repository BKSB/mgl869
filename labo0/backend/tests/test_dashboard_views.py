"""Vues construites sur un vrai jumeau et un vrai service d'alertes."""

from dataclasses import replace

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
OCCUPANCY = "gridd.obs.occupancy.count"
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
                floor="É1", building="Pavillon A", space="A-1540",
                unit="ppm") -> dict:
    """Metadonnees gridd ; `room=None` : capteur sans lieu (camera)."""
    metadata = {}
    if room is not None:
        metadata = {"zone": {"id": room.lower().replace(" ", "-"),
                             "label": room},
                    "storey": {"label": floor},
                    "building": {"label": building}}
        if space:
            metadata["space"] = {"id": space, "label": "GRIDD"}
    return {
        "topic": topic, "partition": 0, "offset": offset, "timestamp_ms": ts,
        "key": None,
        "value": {"node_id": node, "type": "mesure", "value": valeur,
                  "unit": unit, "metadata": metadata},
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
        assert view["site"] == "Local A-1540"
        assert view["people"] is None
        assert view["alerts_enabled"] is True
        assert view["alerts_active"] == 1
        assert [r["id"] for r in view["ranges"]] == ["15m", "1h", "24h"]
        assert view["view"] == "rooms"

    def test_unknown_view_falls_back_to_rooms(self, office):
        assert office.render(view="inconnue")["view"] == "rooms"
        assert office.render(view=3)["view"] == "rooms"

    async def test_site_from_spaces_then_buildings(self, world):
        await world.measure(CO2, "a", 1, space="A-1541")
        await world.measure(CO2, "b", 1, space="A-1540")
        assert world.render()["site"] == "Locaux A-1540, A-1541"

        other = World()
        await other.measure(CO2, "a", 1, space="", building="Pavillon B")
        await other.measure(CO2, "b", 1, space="", building="Pavillon A")
        await other.measure(CO2, "c", 1, room=None)
        assert other.render()["site"] == "Pavillon A, Pavillon B"
        assert World().render()["site"] == ""

    async def test_acknowledged_alerts_leave_the_badge(self, office):
        office.alerts.acknowledge(f"{CO2}|co2-a", "K. Brou", at_ms=NOW)
        assert office.render()["alerts_active"] == 0


class TestPeople:
    async def test_sum_of_occupancy_sensors(self, office):
        await office.measure(OCCUPANCY, "occupancy-camera", 2, NOW - 60_000,
                             room=None, unit="person")
        await office.measure(OCCUPANCY, "counter-b", 21, NOW - 10, room="Bureau",
                             unit="person")
        assert office.render()["people"] == {
            "count_text": "23",
            "label": "personnes dans le local",
            "updated_ms": NOW - 10,
        }

    async def test_singular(self, world):
        await world.measure(OCCUPANCY, "cam", 1, room=None, unit="person")
        assert world.render()["people"]["label"] == "personne dans le local"
        await world.measure(OCCUPANCY, "cam", 0, NOW + 1, room=None, unit="person")
        assert world.render()["people"]["count_text"] == "0"

    async def test_camera_tile_without_unit(self, world):
        await world.measure(OCCUPANCY, "cam", 2, room=None, unit="person")
        tile = world.render(view="rooms", room=NO_PLACE_ID)["room"]["sensors"][0]
        assert (tile["label"], tile["value_text"], tile["unit"]) == \
            ("Occupation", "2", "")


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
        assert room["building"] == "Pavillon A"
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
                {"severity": "warning", "direction": "above", "value": 1000.0,
                 "text": f"W > 1{G}000{F}ppm", "short": f"W > 1{G}000",
                 "label": f"Seuil warning 1{G}000"},
                {"severity": "critical", "direction": "above", "value": 1500.0,
                 "text": f"E > 1{G}500{F}ppm", "short": f"E > 1{G}500",
                 "label": f"Seuil erreur 1{G}500"},
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
        record["offset"] += 100
        world.twin.ingest(CO2, record, NOW)
        assert [r["name"] for r in world.render()["rooms"]] == ["Nouveau nom"]

    def test_no_sensor(self, world):
        assert world.render(view="rooms") == {
            **world.render(view="rooms"), "rooms": [], "room": None}

    async def test_room_status_is_the_worst(self, world):
        """Seuls les capteurs dans le pire etat sont comptes : le warning
        n'est pas une erreur."""
        await world.measure(CO2, "a", 1600)
        await world.measure(CO2, "b", 1200)
        await world.measure(CO2, "c", 400)
        room = world.render(view="rooms")["room"]
        assert (room["status"], room["status_label"]) == \
            ("critical", "Erreur · 1 capteur")

        await world.measure(CO2, "b", 1700)
        assert world.render(view="rooms")["room"]["status_label"] == \
            "Erreur · 2 capteurs"

    async def test_sensor_without_place_hidden_from_menu(self, world):
        await world.measure(CO2, "a", 1, room=None)
        await world.measure(CO2, "b", 1)

        view = world.render(view="rooms")
        assert [r["id"] for r in view["rooms"]] == ["salle-a"]
        assert view["room"]["id"] == "salle-a"
        # Reste accessible par son id (tuile Par capteur, « Voir la piece »)
        detail = world.render(view="rooms", room=NO_PLACE_ID)["room"]
        assert (detail["name"], [s["id"] for s in detail["sensors"]]) == \
            ("Sans pièce", ["a"])

    async def test_only_sensors_without_place(self, world):
        await world.measure(CO2, "a", 1, room=None)
        view = world.render(view="rooms")
        assert (view["rooms"], view["room"]) == ([], None)

    async def test_units_mapped_for_display(self, world):
        await world.measure(TEMPERATURE, "t", 27, unit="C")
        tile = world.render(view="rooms")["room"]["sensors"][0]
        assert tile["unit"] == "°C"
        assert tile["thresholds"][1]["text"] == f"W > 26{F}°C"
        metric = world.render(view="metric", metric="temperature")["metric"]
        assert (metric["unit"], metric["thresholds"][1]["text"]) == \
            ("°C", f"W > 26{F}°C")


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

    async def test_occupancy_has_no_tab(self, world):
        await world.measure(OCCUPANCY, "cam", 2, room=None, unit="person")
        ctx = replace(world.context(), topics=[*TOPICS, OCCUPANCY])

        view = views.render(ctx, {"view": "metric", "metric": "occupancy"})

        assert [m["id"] for m in view["metrics"]] == ["co2", "temperature"]
        assert view["metric"]["id"] == "co2"
        assert view["people"]["count_text"] == "2"  # en-tete seulement

        ctx = replace(ctx, topics=[OCCUPANCY])
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

    async def test_units_mapped_for_display(self, world):
        await world.measure(TEMPERATURE, "t", 26.8, unit="C")
        (row,) = world.render(view="alerts")["alerts"]
        assert (row["value_text"], row["threshold_text"]) == \
            (f"26,8{F}°C", f"W > 26{F}°C")
        event = world.alerts.recent_events()[0]
        assert views.toast(event, None)["text"] == f"> seuil warning 26{F}°C"


@pytest.fixture
async def history(world):
    """co2-a : un point par heure sur 3 jours, un pic critique il y a 30 h
    (alerte resolue par la derniere mesure)."""
    for k in range(72, 0, -1):
        await world.measure(CO2, "co2-a", 500 + (k % 5) * 10, NOW - k * HOUR)
    await world.measure(CO2, "co2-a", 1600, NOW - 30 * HOUR)
    await world.measure(CO2, "co2-a", 520, NOW)
    return world


class TestChartView:
    def test_default_range_30d(self, history):
        chart = history.render(view="chart", metric="co2", sensor="co2-a")["chart"]
        assert (chart["metric"], chart["label"], chart["unit"]) == \
            ("co2", "CO₂", "ppm")
        assert chart["sensor_id"] == "co2-a"
        assert chart["room"]["name"] == "Salle A"
        assert (chart["value_text"], chart["status"], chart["updated_ms"]) == \
            ("520", "normal", NOW)
        assert (chart["range"], chart["range_label"]) == ("30d", "30 j")
        assert [r["id"] for r in chart["ranges"]] == ["24h", "7d", "30d"]
        assert chart["overview_label"] == "30 derniers jours"
        assert chart["span"] == [NOW - 30 * 24 * HOUR, NOW]
        assert chart["zoom"] is None
        assert chart["thresholds"][1]["label"] == f"Seuil erreur 1{G}500"
        assert chart["csv_url"] == "/api/chart.csv?metric=co2&sensor=co2-a&range=30d"
        # 72 heures pleines + l'heure courante ; moyennes horaires avec leur etat
        series = chart["series"]
        assert len(series) == 73
        hour = NOW - 30 * HOUR
        peak = next(p for p in series if p[0] == hour - hour % HOUR)
        assert peak[1:] == [1050.0, "warning", f"1{G}050"]
        assert series[-1][1:] == [520.0, "normal", "520"]
        assert chart["stats"] == {
            "scope": "30 j",
            "min": {"text": "500", "status": "normal"},
            "max": {"text": f"1{G}600", "status": "critical"},
            "mean": {"text": "534"},  # 39 550 / 74 mesures
            "alerts": [{"status": "critical", "text": "1 erreur"}],
        }

    def test_zoom(self, history):
        a, b = NOW - 10 * HOUR, NOW - 2 * HOUR
        chart = history.render(view="chart", metric="co2", sensor="co2-a",
                               range="30d", **{"from": str(a), "to": b})["chart"]
        assert chart["zoom"] == [a, b]
        assert chart["stats"]["scope"] == "zoom"
        assert chart["stats"]["max"] == {"text": "540", "status": "normal"}
        assert chart["stats"]["alerts"] == [{"status": "normal", "text": "aucune"}]
        assert len(chart["series"]) == 73  # la serie reste celle de la plage
        assert chart["csv_url"].endswith(f"&from={a}&to={b}")

    @pytest.mark.parametrize("window", [
        {"from": "x", "to": 5},                    # illisible
        {"from": NOW - 40 * 24 * HOUR, "to": NOW + HOUR},  # borne = plage entiere
        {"from": NOW - 5000, "to": NOW},           # trop etroite
        {"from": NOW, "to": NOW - HOUR},           # inversee
    ])
    def test_zoom_ignored(self, history, window):
        chart = history.render(view="chart", metric="co2", sensor="co2-a",
                               **window)["chart"]
        assert chart["zoom"] is None
        assert chart["stats"]["scope"] == "30 j"

    def test_zoom_clamped_to_range(self, history):
        chart = history.render(view="chart", metric="co2", sensor="co2-a",
                               **{"from": NOW - 40 * 24 * HOUR, "to": NOW - HOUR})["chart"]
        assert chart["zoom"] == [NOW - 30 * 24 * HOUR, NOW - HOUR]

    def test_range_24h_from_raw_points(self, history):
        chart = history.render(view="chart", metric="co2", sensor="co2-a",
                               range="24h")["chart"]
        assert chart["span"] == [NOW - 24 * HOUR, NOW]
        assert chart["overview_label"] == "24 dernières heures"
        # Cases de 10 min : un point par heure -> 24 heures pleines + l'instant
        assert len(chart["series"]) == 25
        start = NOW - 24 * HOUR
        assert chart["series"][0][0] == start - start % (10 * 60_000)
        assert chart["stats"]["scope"] == "24 h"
        assert chart["stats"]["alerts"] == [{"status": "critical", "text": "1 erreur"}]

    async def test_no_data_on_range(self, world):
        await world.measure(CO2, "old", 500, NOW - 3 * 24 * HOUR)
        chart = world.render(view="chart", metric="co2", sensor="old",
                             range="24h")["chart"]
        assert (chart["series"], chart["stats"]) == ([], None)

    def test_unknown_sensor(self, history):
        assert history.render(view="chart", metric="co2", sensor="x")["chart"] is None
        assert history.render(view="chart", metric="x", sensor="co2-a")["chart"] is None
        assert history.render(view="chart")["chart"] is None

    async def test_alert_episodes_counted_once(self, world):
        for valeur, ts in [(1200, NOW - 5 * HOUR), (1600, NOW - 4 * HOUR),
                           (1200, NOW - 3 * HOUR), (900, NOW - 2 * HOUR),
                           (1100, NOW - HOUR)]:
            await world.measure(CO2, "a", valeur, ts)
        chart = world.render(view="chart", metric="co2", sensor="a")["chart"]
        # Episode 1 : warning -> critical -> warning -> resolu ; episode 2 : actif
        assert chart["stats"]["alerts"] == [
            {"status": "warning", "text": "1 warning"},
            {"status": "critical", "text": "1 erreur"},
        ]

    def test_csv(self, history):
        name, text = views.chart_csv(history.context(), {
            "metric": "co2", "sensor": "co2-a", "range": "30d",
            "from": NOW - 31 * HOUR, "to": NOW - 29 * HOUR})
        assert name == "co2-co2-a-30d.csv"
        lines = text.splitlines()
        assert lines[0] == "timestamp_ms,datetime_utc,mean,min,max,count"
        peak = next(line for line in lines if line.endswith(",2"))
        hour = NOW - 30 * HOUR
        assert peak.startswith(f"{hour - hour % HOUR},")
        assert peak.endswith(",1050.0,500.0,1600.0,2")
        assert "T" in peak.split(",")[1] and peak.split(",")[1].endswith("+00:00")
        assert views.chart_csv(history.context(), {"metric": "co2"}) is None


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
