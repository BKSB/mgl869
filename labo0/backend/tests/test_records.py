from app.data_management.records import NO_SENSOR_ID, SeenOffsets, sensor_id
from tests.conftest import make_record


class TestSeenOffsets:
    def test_new_then_duplicate(self):
        seen = SeenOffsets()
        assert seen.add(0, 5)
        assert not seen.add(0, 5)
        assert seen.add(1, 5)  # autre partition
        assert seen.to_dict() == {"0": [[5, 5]], "1": [[5, 5]]}

    def test_merges_adjacent_offsets(self):
        seen = SeenOffsets()
        for offset in (1, 2, 3):
            assert seen.add(0, offset)
        assert seen.to_dict() == {"0": [[1, 3]]}
        assert seen.add(0, 5)
        assert seen.to_dict() == {"0": [[1, 3], [5, 5]]}
        assert seen.add(0, 4)  # comble le trou : un seul intervalle
        assert seen.to_dict() == {"0": [[1, 5]]}

    def test_any_order(self):
        seen = SeenOffsets()
        for offset in (10, 5, 7, 6):
            assert seen.add(0, offset)
        assert seen.to_dict() == {"0": [[5, 7], [10, 10]]}
        assert not seen.add(0, 6)
        assert not seen.add(0, 10)
        assert seen.add(0, 8)
        assert seen.to_dict() == {"0": [[5, 8], [10, 10]]}

    def test_restored(self):
        seen = SeenOffsets({"0": [[1, 3]]})
        assert not seen.add(0, 2)
        assert seen.add(0, 4)
        assert seen.to_dict() == {"0": [[1, 4]]}


class TestSensorId:
    def test_node_id_from_payload(self):
        assert sensor_id(make_record(node_id="n42", key="k")) == "n42"

    def test_non_string_node_id_converted(self):
        assert sensor_id({"value": {"node_id": 42}, "key": None}) == "42"

    def test_falls_back_to_kafka_key(self):
        assert sensor_id(make_record(node_id=None, key="k1")) == "k1"

    def test_non_dict_payload(self):
        record = {"value": "texte brut", "key": "k2"}
        assert sensor_id(record) == "k2"

    def test_without_node_id_or_key(self):
        assert sensor_id(make_record(node_id=None)) == NO_SENSOR_ID == \
            "_sans_node_id"
