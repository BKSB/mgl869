"""Tests du hub de diffusion WebSocket (historique par capteur, rejeu,
deduplication, clients lents)."""

import asyncio

from app.data_management.data_distribution.websocket_hub import TopicHub
from tests.conftest import make_record


def drain(queue: asyncio.Queue) -> list[dict]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


class TestSensorId:
    def test_node_id_du_payload(self):
        assert TopicHub._sensor_id(make_record(node_id="n42", key="k")) == "n42"

    def test_repli_sur_la_cle_kafka(self):
        assert TopicHub._sensor_id(make_record(node_id=None, key="k1")) == "k1"

    def test_payload_non_dict(self):
        record = {"value": "texte brut", "key": "k2"}
        assert TopicHub._sensor_id(record) == "k2"

    def test_sans_node_id_ni_cle(self):
        assert TopicHub._sensor_id(make_record(node_id=None)) == "_sans_node_id"


class TestSubscribe:
    def test_topic_sans_historique(self):
        queue = TopicHub().subscribe("t")
        assert queue.empty()

    def test_rejeu_fusionne_par_ordre_chronologique(self):
        hub = TopicHub()
        hub.publish("t", make_record("a", offset=0, timestamp_ms=300))
        hub.publish("t", make_record("b", offset=1, timestamp_ms=100))
        hub.publish("t", make_record("a", offset=2, timestamp_ms=200))

        replay = drain(hub.subscribe("t"))

        assert [r["timestamp_ms"] for r in replay] == [100, 200, 300]

    def test_rejeu_limite_au_topic_demande(self):
        hub = TopicHub()
        hub.publish("t1", make_record(offset=0))
        hub.publish("t2", make_record(offset=1))

        replay = drain(hub.subscribe("t1"))

        assert [r["offset"] for r in replay] == [0]

    def test_file_dimensionnee_pour_rejeu_plus_marge(self):
        hub = TopicHub()
        for i in range(3):
            hub.publish("t", make_record(offset=i))
        queue = hub.subscribe("t")
        assert queue.maxsize == 3 + TopicHub.CLIENT_QUEUE_MARGIN


class TestPublish:
    def test_diffuse_aux_abonnes_du_topic_seulement(self):
        hub = TopicHub()
        q1, q2 = hub.subscribe("t"), hub.subscribe("t")
        other = hub.subscribe("autre")

        record = make_record(offset=7)
        hub.publish("t", record)

        assert drain(q1) == [record]
        assert drain(q2) == [record]
        assert drain(other) == []

    def test_desabonnement(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.unsubscribe("t", queue)

        hub.publish("t", make_record())

        assert queue.empty()

    def test_desabonnement_topic_inconnu_sans_erreur(self):
        TopicHub().unsubscribe("inconnu", asyncio.Queue())

    def test_deduplication_partition_offset(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=1, offset=5))

        assert len(drain(queue)) == 2
        assert len(drain(hub.subscribe("t"))) == 2

    def test_historique_borne_par_capteur(self):
        hub = TopicHub(history_per_sensor={"t": 2})
        for i in range(5):
            hub.publish("t", make_record("bavard", offset=i, timestamp_ms=i))
        hub.publish("t", make_record("lent", offset=100, timestamp_ms=0))

        replay = drain(hub.subscribe("t"))

        bavard = [r["offset"] for r in replay if r["value"]["node_id"] == "bavard"]
        lent = [r["offset"] for r in replay if r["value"]["node_id"] == "lent"]
        # Le capteur bavard ne garde que ses 2 derniers messages et n'evince
        # pas l'historique du capteur lent
        assert bavard == [3, 4]
        assert lent == [100]

    def test_taille_historique_par_defaut(self):
        hub = TopicHub(default_history=3)
        for i in range(10):
            hub.publish("t", make_record(offset=i, timestamp_ms=i))
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [7, 8, 9]

    def test_client_lent_perd_les_plus_anciens(self):
        hub = TopicHub()
        hub.CLIENT_QUEUE_MARGIN = 2
        queue = hub.subscribe("t")  # maxsize = 0 rejeu + 2

        for i in range(4):
            hub.publish("t", make_record(offset=i))

        assert [r["offset"] for r in drain(queue)] == [2, 3]
