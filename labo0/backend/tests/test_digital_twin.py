import pytest

from app.data_management.data_processing.digital_twin import (
    HISTORY_MS,
    NO_PLACE_ID,
    UNKNOWN_PLACE,
    DigitalTwin,
    Place,
    place_from,
)
from tests.conftest import make_measurement

CO2 = "gridd.obs.environmental.co2"
NOW = 10 * HISTORY_MS


def record(valeur=400, ts=NOW, **kwargs) -> dict:
    return make_measurement(valeur, timestamp_ms=ts, topic=CO2, **kwargs)


class TestPlace:
    def test_zone_before_space(self):
        assert place_from(record()["value"]) == Place("z1", "Zone A")

    def test_space_without_zone(self):
        assert place_from(record(zone=None)["value"]) == Place("s1", "Salle 101")

    def test_floor_and_building(self):
        payload = record()["value"]
        payload["metadata"]["storey"] = {"id": "e3", "label": "Étage 3"}
        payload["metadata"]["building"] = {"label": "Local A-3120"}
        assert place_from(payload) == Place("z1", "Zone A", "Étage 3",
                                            "Local A-3120")

    def test_label_or_id_alone(self):
        assert place_from({"metadata": {"zone": {"label": "Nord"}}}) == \
            Place("Nord", "Nord")
        assert place_from({"metadata": {"zone": {"id": 7}}}) == Place("7", "7")

    @pytest.mark.parametrize("payload", [
        {},
        {"metadata": None},
        {"metadata": {"zone": {"label": ""}, "space": "Salle"}},
        {"metadata": {"storey": {"label": "E1"}}},
    ])
    def test_unknown_place(self, payload):
        assert place_from(payload) == UNKNOWN_PLACE
        assert UNKNOWN_PLACE.id == NO_PLACE_ID


class TestIngest:
    def test_measurement_recorded(self):
        twin = DigitalTwin()

        assert twin.ingest(CO2, record(400, ts=NOW - 1000), now_ms=NOW)

        (sensor,) = twin.sensors()
        assert (sensor.topic, sensor.id, sensor.unit) == (CO2, "n1", "ppm")
        assert (sensor.value, sensor.updated_ms) == (400.0, NOW - 1000)
        assert sensor.place == Place("z1", "Zone A")
        assert sensor.points == [(NOW - 1000, 400.0)]
        assert twin.sensor(CO2, "n1") is sensor
        assert twin.sensor(CO2, "n2") is None

    @pytest.mark.parametrize("valeur", ["400", None, True])
    def test_non_numeric_value_ignored(self, valeur):
        twin = DigitalTwin()
        assert not twin.ingest(CO2, record(valeur), now_ms=NOW)
        assert twin.sensors() == []

    def test_non_measurement_ignored(self):
        twin = DigitalTwin()
        brut = record()
        brut["value"] = "texte brut"
        sans_date = record()
        sans_date["timestamp_ms"] = None
        assert not twin.ingest(CO2, brut, now_ms=NOW)
        assert not twin.ingest(CO2, sans_date, now_ms=NOW)
        assert twin.sensors() == []

    def test_older_than_history_ignored(self):
        twin = DigitalTwin()
        assert not twin.ingest(CO2, record(ts=NOW - HISTORY_MS - 1), now_ms=NOW)
        assert twin.ingest(CO2, record(ts=NOW - HISTORY_MS), now_ms=NOW)

    def test_latest_measurement_wins_whatever_the_order(self):
        twin = DigitalTwin()
        twin.ingest(CO2, record(2, ts=200, zone="Zone B"), now_ms=1000)
        twin.ingest(CO2, record(1, ts=100, zone="Zone A", unit="PPM"),
                    now_ms=1000)

        (sensor,) = twin.sensors()
        assert (sensor.value, sensor.updated_ms, sensor.unit) == (2.0, 200, "ppm")
        assert sensor.place.name == "Zone B"
        assert sensor.points == [(100, 1.0), (200, 2.0)]

    def test_metadata_follow_latest_measurement(self):
        twin = DigitalTwin()
        twin.ingest(CO2, record(1, ts=100), now_ms=1000)
        twin.ingest(CO2, record(2, ts=200, zone="Zone B"), now_ms=1000)
        assert twin.sensors()[0].place == Place("z1", "Zone B")

    def test_expired_points_dropped(self):
        twin = DigitalTwin(history_ms=1000)
        twin.ingest(CO2, record(1, ts=NOW - 900), now_ms=NOW)
        twin.ingest(CO2, record(2, ts=NOW), now_ms=NOW)
        twin.ingest(CO2, record(3, ts=NOW + 200), now_ms=NOW + 200)

        (sensor,) = twin.sensors()
        assert sensor.points == [(NOW, 2.0), (NOW + 200, 3.0)]

    def test_unit_missing(self):
        twin = DigitalTwin()
        measurement = record()
        del measurement["value"]["unit"]
        twin.ingest(CO2, measurement, now_ms=NOW)
        assert twin.sensors()[0].unit == ""

    def test_sensors_keyed_by_topic_and_id(self):
        twin = DigitalTwin()
        twin.ingest(CO2, record(node_id="n1"), now_ms=NOW)
        twin.ingest(CO2, record(node_id="n2"), now_ms=NOW)
        twin.ingest("autre", record(node_id="n1"), now_ms=NOW)
        assert sorted((s.topic, s.id) for s in twin.sensors()) == \
            sorted([(CO2, "n1"), (CO2, "n2"), ("autre", "n1")])


class TestWindow:
    def test_points_from_since(self):
        twin = DigitalTwin()
        for ts in (1, 2, 3, 4, 5):
            twin.ingest(CO2, record(ts, ts=ts), now_ms=10)
        (sensor,) = twin.sensors()
        assert sensor.window(3) == [(3, 3.0), (4, 4.0), (5, 5.0)]
        assert sensor.window(6) == []
        assert sensor.window(0) == sensor.points
