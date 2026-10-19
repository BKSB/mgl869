import asyncio

from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from tests.conftest import drain, make_record


def with_sensor_id(record: dict, sensor: str = "n1") -> dict:
    """Record tel que diffuse par le hub."""
    return {**record, "sensor_id": sensor}


class TestSensorIdentification:
    def test_history_per_sensor_uses_shared_id(self):
        """records.sensor_id : node_id, sinon cle Kafka (comme les alertes)."""
        hub = TopicHub(history_per_sensor={"t": 1})
        hub.publish("t", make_record(node_id=None, key="k1", offset=0))
        hub.publish("t", make_record(node_id="k1", offset=1))
        hub.publish("t", make_record(node_id="n2", offset=2))

        assert sorted(r["offset"] for r in drain(hub.subscribe("t"))) == [1, 2]

    def test_records_broadcast_with_sensor_id(self):
        """Les clients n'ont pas a redefinir l'identite d'un capteur."""
        hub = TopicHub()
        queue = hub.subscribe("t")
        sans_id = make_record(node_id=None, key=None, offset=0)
        par_cle = make_record(node_id=None, key="k1", offset=1)
        vide = make_record(node_id="", key="k2", offset=2)

        for record in (sans_id, par_cle, vide):
            hub.publish("t", record)

        assert [r["sensor_id"] for r in drain(queue)] == \
            ["_sans_node_id", "k1", "k2"]
        # Le record partage avec les autres observateurs n'est pas modifie
        assert "sensor_id" not in sans_id


class TestSubscribe:
    def test_topic_without_history(self):
        queue = TopicHub().subscribe("t")
        assert queue.empty()

    def test_replay_merged_chronologically(self):
        hub = TopicHub()
        hub.publish("t", make_record("a", offset=0, timestamp_ms=300))
        hub.publish("t", make_record("b", offset=1, timestamp_ms=100))
        hub.publish("t", make_record("a", offset=2, timestamp_ms=200))

        replay = drain(hub.subscribe("t"))

        assert [r["timestamp_ms"] for r in replay] == [100, 200, 300]

    def test_replay_limited_to_requested_topic(self):
        hub = TopicHub()
        hub.publish("t1", make_record(offset=0))
        hub.publish("t2", make_record(offset=1))

        replay = drain(hub.subscribe("t1"))

        assert [r["offset"] for r in replay] == [0]

    def test_queue_sized_for_replay_plus_margin(self):
        hub = TopicHub()
        for i in range(3):
            hub.publish("t", make_record(offset=i))
        queue = hub.subscribe("t")
        assert queue.maxsize == 3 + TopicHub.CLIENT_QUEUE_MARGIN


class TestPublish:
    def test_broadcasts_to_topic_subscribers_only(self):
        hub = TopicHub()
        q1, q2 = hub.subscribe("t"), hub.subscribe("t")
        other = hub.subscribe("autre")

        record = make_record(offset=7)
        hub.publish("t", record)

        assert drain(q1) == [with_sensor_id(record)]
        assert drain(q2) == [with_sensor_id(record)]
        assert drain(other) == []

    def test_unsubscribe(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.unsubscribe("t", queue)

        hub.publish("t", make_record())

        assert queue.empty()

    def test_unsubscribe_unknown_topic_without_error(self):
        TopicHub().unsubscribe("inconnu", asyncio.Queue())

    def test_deduplication_partition_offset(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=1, offset=5))

        assert len(drain(queue)) == 2
        assert len(drain(hub.subscribe("t"))) == 2

    def test_history_bounded_per_sensor(self):
        hub = TopicHub(history_per_sensor={"t": 2})
        for i in range(5):
            hub.publish("t", make_record("bavard", offset=i, timestamp_ms=i))
        hub.publish("t", make_record("lent", offset=100, timestamp_ms=0))

        replay = drain(hub.subscribe("t"))

        bavard = [r["offset"] for r in replay if r["value"]["node_id"] == "bavard"]
        lent = [r["offset"] for r in replay if r["value"]["node_id"] == "lent"]
        # Le bavard garde ses 2 derniers messages sans evincer le capteur lent
        assert bavard == [3, 4]
        assert lent == [100]

    def test_deduplication_with_full_history(self):
        """Doublon d'un message conserve ignore ; message evince accepte."""
        hub = TopicHub(history_per_sensor={"t": 2})
        for i in range(3):  # l'offset 0 est evince
            hub.publish("t", make_record(offset=i, timestamp_ms=i))
        queue = hub.subscribe("t")
        drain(queue)

        hub.publish("t", make_record(offset=2, timestamp_ms=2))
        hub.publish("t", make_record(offset=0, timestamp_ms=0))

        assert [r["offset"] for r in drain(queue)] == [0]
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [0, 2]

    def test_zero_size_history(self):
        """Rien n'est historise ni dedoublonne : tout est diffuse."""
        hub = TopicHub(history_per_sensor={"t": 0})
        queue = hub.subscribe("t")

        hub.publish("t", make_record(offset=1))
        hub.publish("t", make_record(offset=1))

        assert len(drain(queue)) == 2
        assert drain(hub.subscribe("t")) == []

    def test_default_history_size(self):
        hub = TopicHub(default_history=3)
        for i in range(10):
            hub.publish("t", make_record(offset=i, timestamp_ms=i))
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [7, 8, 9]

    def test_slow_client_drops_oldest(self):
        hub = TopicHub()
        hub.CLIENT_QUEUE_MARGIN = 2
        queue = hub.subscribe("t")  # maxsize = 0 rejeu + 2

        for i in range(4):
            hub.publish("t", make_record(offset=i))

        assert [r["offset"] for r in drain(queue)] == [2, 3]


class TestBusObserver:
    async def test_on_record_broadcasts_and_stores(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        record = make_record(offset=1)

        await hub.on_record("t", record, replay=False)

        assert drain(queue) == [with_sensor_id(record)]
        assert drain(hub.subscribe("t")) == [with_sensor_id(record)]

    async def test_replayed_records_also_broadcast_and_stored(self):
        """Remplir l'historique au demarrage est le role du prechauffage."""
        hub = TopicHub()
        queue = hub.subscribe("t")

        await hub.on_record("t", make_record(offset=1), replay=True)

        assert [r["offset"] for r in drain(queue)] == [1]
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [1]

    async def test_on_record_idempotent(self):
        """Relu par le prechauffage puis consomme : diffuse une seule fois."""
        hub = TopicHub()
        queue = hub.subscribe("t")

        await hub.on_record("t", make_record(offset=5), replay=True)
        await hub.on_record("t", make_record(offset=5), replay=False)

        assert len(drain(queue)) == 1
        assert len(drain(hub.subscribe("t"))) == 1

    async def test_subscribed_to_bus(self):
        hub = TopicHub()
        queue_a, queue_b = hub.subscribe("a"), hub.subscribe("b")
        bus = RecordBus()
        bus.subscribe(hub)

        await bus.publish("a", make_record(topic="a", offset=1))
        await bus.publish("b", make_record(topic="b", offset=2), replay=True)

        assert [r["offset"] for r in drain(queue_a)] == [1]
        assert [r["offset"] for r in drain(queue_b)] == [2]
