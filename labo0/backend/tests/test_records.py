from app.data_management.records import NO_SENSOR_ID, sensor_id
from tests.conftest import make_record


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
