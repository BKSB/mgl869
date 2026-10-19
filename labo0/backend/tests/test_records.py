"""Tests des helpers partages : identification du capteur d'un record et
politique des files clientes (le plus ancien est jete)."""

import asyncio

from app.data_management.data_distribution.queues import offer_dropping_oldest
from app.data_management.records import NO_SENSOR_ID, sensor_id
from tests.conftest import make_record


class TestSensorId:
    def test_node_id_du_payload(self):
        assert sensor_id(make_record(node_id="n42", key="k")) == "n42"

    def test_node_id_non_textuel_converti(self):
        assert sensor_id({"value": {"node_id": 42}, "key": None}) == "42"

    def test_repli_sur_la_cle_kafka(self):
        assert sensor_id(make_record(node_id=None, key="k1")) == "k1"

    def test_payload_non_dict(self):
        record = {"value": "texte brut", "key": "k2"}
        assert sensor_id(record) == "k2"

    def test_sans_node_id_ni_cle(self):
        assert sensor_id(make_record(node_id=None)) == NO_SENSOR_ID == \
            "_sans_node_id"


class TestOfferDroppingOldest:
    def test_depot_simple(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        offer_dropping_oldest(queue, 1)
        assert queue.get_nowait() == 1

    def test_file_pleine_jette_le_plus_ancien(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        for item in range(4):
            offer_dropping_oldest(queue, item)
        assert [queue.get_nowait(), queue.get_nowait()] == [2, 3]
        assert queue.empty()

    def test_file_non_bornee(self):
        queue: asyncio.Queue = asyncio.Queue()
        for item in range(5):
            offer_dropping_oldest(queue, item)
        assert queue.qsize() == 5
