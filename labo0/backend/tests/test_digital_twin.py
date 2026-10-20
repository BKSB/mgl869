import itertools
import json

import pytest

from app.data_management.data_processing.digital_twin import (
    HISTORY_MS,
    HOUR_MS,
    NO_PLACE_ID,
    RAW_MS,
    UNKNOWN_PLACE,
    DigitalTwin,
    Place,
    place_from,
)
from tests.conftest import make_measurement

CO2 = "gridd.obs.environmental.co2"
NOW = 10 * HISTORY_MS
_OFFSETS = itertools.count()


def record(valeur=400, ts=NOW, **kwargs) -> dict:
    """Offset unique par defaut : le jumeau ignore les offsets deja vus."""
    kwargs.setdefault("offset", next(_OFFSETS))
    return make_measurement(valeur, timestamp_ms=ts, topic=CO2, **kwargs)


class TestPlace:
    def test_zone_before_space(self):
        assert place_from(record()["value"]) == Place("z1", "Zone A", space="s1")

    def test_space_without_zone(self):
        assert place_from(record(zone=None)["value"]) == \
            Place("s1", "Salle 101", space="s1")

    def test_floor_building_and_space(self):
        payload = record()["value"]
        payload["metadata"]["storey"] = {"id": "1", "label": "1er étage"}
        payload["metadata"]["building"] = {"id": "A", "label": "Pavillon A"}
        payload["metadata"]["space"] = {"id": "A-1540", "label": "GRIDD"}
        assert place_from(payload) == Place("z1", "Zone A", "1er étage",
                                            "Pavillon A", "A-1540")

    def test_label_or_id_alone(self):
        assert place_from({"metadata": {"zone": {"label": "Nord"}}}) == \
            Place("Nord", "Nord")
        assert place_from({"metadata": {"zone": {"id": 7}}}) == Place("7", "7")
        assert place_from({"metadata": {"space": {"label": "Labo"}}}) == \
            Place("Labo", "Labo", space="Labo")

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
        assert sensor.place == Place("z1", "Zone A", space="s1")
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
        assert twin.sensors()[0].place == Place("z1", "Zone B", space="s1")

    def test_expired_points_dropped(self):
        twin = DigitalTwin(history_ms=1000, raw_ms=1000)
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


class TestDedup:
    def test_same_offset_ignored(self):
        twin = DigitalTwin()
        assert twin.ingest(CO2, record(1, ts=100, offset=7), now_ms=1000)
        assert not twin.ingest(CO2, record(2, ts=200, offset=7), now_ms=1000)
        (sensor,) = twin.sensors()
        assert (sensor.value, sensor.points) == (1.0, [(100, 1.0)])

    def test_other_partition_or_topic(self):
        twin = DigitalTwin()
        assert twin.ingest(CO2, record(1, ts=100, offset=7), now_ms=1000)
        assert twin.ingest(CO2, record(2, ts=200, offset=7, partition=1), now_ms=1000)
        assert twin.ingest("autre", record(3, ts=300, offset=7), now_ms=1000)
        assert twin.sensor(CO2, "n1").points == [(100, 1.0), (200, 2.0)]

    def test_offset_seen_whatever_the_payload(self):
        """Prefixe consomme : un record sans mesure compte aussi."""
        twin = DigitalTwin()
        assert not twin.ingest(CO2, record("texte", ts=100, offset=7), now_ms=1000)
        assert not twin.ingest(CO2, record(1, ts=100, offset=7), now_ms=1000)
        assert twin.sensors() == []

    def test_older_offset_accepted(self):
        """Rattrapage derriere le prechauffage : les offsets reviennent en
        arriere mais n'ont jamais ete vus."""
        twin = DigitalTwin()
        assert twin.ingest(CO2, record(1, ts=100, offset=10), now_ms=1000)
        assert twin.ingest(CO2, record(2, ts=50, offset=5), now_ms=1000)
        assert twin.sensor(CO2, "n1").points == [(50, 2.0), (100, 1.0)]

    def test_without_offset_never_deduplicated(self):
        twin = DigitalTwin()
        for _ in range(2):
            assert twin.ingest(CO2, record(1, ts=100, offset=None), now_ms=1000)
        assert len(twin.sensor(CO2, "n1").points) == 2


class TestHours:
    def test_hourly_buckets(self):
        twin = DigitalTwin()
        base = NOW - NOW % HOUR_MS
        for ts, valeur in [(base + 1, 10), (base + 2, 30), (base + HOUR_MS, 5)]:
            twin.ingest(CO2, record(valeur, ts=ts), now_ms=NOW + 2 * HOUR_MS)
        (sensor,) = twin.sensors()
        assert sensor.hours == {base: [2, 40.0, 10.0, 30.0],
                                base + HOUR_MS: [1, 5.0, 5.0, 5.0]}
        assert sensor.hours_since(base + HOUR_MS) == \
            [(base + HOUR_MS, [1, 5.0, 5.0, 5.0])]

    def test_old_measurement_only_in_hours(self):
        twin = DigitalTwin()
        ts = NOW - RAW_MS - 1
        assert twin.ingest(CO2, record(7, ts=ts), now_ms=NOW)
        (sensor,) = twin.sensors()
        assert sensor.points == []
        assert sensor.hours == {ts - ts % HOUR_MS: [1, 7.0, 7.0, 7.0]}
        assert sensor.value == 7.0

    def test_purge(self):
        twin = DigitalTwin(history_ms=3 * HOUR_MS, raw_ms=HOUR_MS)
        twin.ingest(CO2, record(1, ts=NOW - 2 * HOUR_MS), now_ms=NOW)
        twin.ingest(CO2, record(2, ts=NOW), now_ms=NOW)
        (sensor,) = twin.sensors()
        assert len(sensor.hours) == 2 and len(sensor.points) == 1

        twin.ingest(CO2, record(3, ts=NOW + 2 * HOUR_MS), now_ms=NOW + 2 * HOUR_MS)
        assert sorted(sensor.hours) == [h - h % HOUR_MS for h in (NOW, NOW + 2 * HOUR_MS)]
        assert sensor.points == [(NOW + 2 * HOUR_MS, 3.0)]


class TestSnapshot:
    def test_round_trip(self):
        twin = DigitalTwin()
        twin.ingest(CO2, record(1, ts=NOW - 10, offset=3), now_ms=NOW)
        twin.ingest(CO2, record(2, ts=NOW, offset=4, zone="Zone B"), now_ms=NOW)
        twin.ingest("autre", record(5, ts=NOW, offset=1, node_id="n9"), now_ms=NOW)

        data = json.loads(json.dumps(twin.to_dict()))
        assert data["seen"] == {CO2: {"0": [[3, 4]]}, "autre": {"0": [[1, 1]]}}
        restored = DigitalTwin()
        assert restored.restore(data, NOW) == 2

        sensor = restored.sensor(CO2, "n1")
        assert sensor.to_dict() == twin.sensor(CO2, "n1").to_dict()
        assert sensor.place == Place("z1", "Zone B", space="s1")
        assert restored.sensor("autre", "n9").value == 5.0
        # La deduplication survit : l'offset 4 reste connu
        assert not restored.ingest(CO2, record(9, ts=NOW + 1, offset=4), now_ms=NOW + 1)
        assert restored.ingest(CO2, record(9, ts=NOW + 1, offset=5), now_ms=NOW + 1)

    def test_expired_on_restore(self):
        twin = DigitalTwin()
        twin.ingest(CO2, record(1, ts=NOW), now_ms=NOW)
        restored = DigitalTwin()
        restored.restore(twin.to_dict(), NOW + RAW_MS + 1)
        sensor = restored.sensor(CO2, "n1")
        assert sensor.points == [] and len(sensor.hours) == 1
        restored.restore(twin.to_dict(), NOW + HISTORY_MS + 1)
        assert restored.sensor(CO2, "n1").hours == {}

    def test_invalid_entries_ignored(self):
        twin = DigitalTwin()
        assert twin.restore({}, NOW) == 0
        assert twin.restore({"sensors": [{"topic": CO2}, "x", None]}, NOW) == 0
        assert twin.sensors() == []
