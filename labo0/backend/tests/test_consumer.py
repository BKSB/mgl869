import asyncio
import functools
import sqlite3

import pytest
from aiokafka.structs import TopicPartition

from app.data_management.data_acquisition import consumer as consumer_module
from app.data_management.data_acquisition.consumer import (
    consume_topic,
    record_from_msg,
)
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from app.data_management.records import HISTORY_MS, HOUR_MS
from tests.conftest import (
    Collector,
    FailingObserver,
    SpyObserver,
    make_measurement,
    make_msg,
)

NOW = 10 * HISTORY_MS
MEASUREMENT = b'{"node_id": "n1", "value": 400, "unit": "ppm"}'


class TestRecordFromMsg:
    def test_json_message(self):
        msg = make_msg(topic="t", partition=2, offset=9, timestamp=123,
                       key=b"capteur", value=b'{"node_id": "n1", "v": 1.5}')
        assert record_from_msg(msg) == {
            "topic": "t",
            "partition": 2,
            "offset": 9,
            "timestamp_ms": 123,
            "key": "capteur",
            "value": {"node_id": "n1", "v": 1.5},
        }

    def test_non_json_message_kept_as_is(self):
        record = record_from_msg(make_msg(value=b"pas du json"))
        assert record["value"] == "pas du json"

    def test_missing_value_and_key(self):
        record = record_from_msg(make_msg(key=None, value=None))
        assert record["key"] is None
        assert record["value"] is None

    def test_invalid_utf8_replaced(self):
        record = record_from_msg(make_msg(key=b"\xff", value=b"\xff"))
        assert record["key"] == "�"
        assert record["value"] == "�"


class FakeConsumer:
    """getmany() livre `messages` par lots de `batch_size` (tout d'un coup par
    defaut), puis signale `idle` et ne rend plus rien. `journal`, partage avec
    des observateurs, recoit "commit" a chaque commit."""
    instances: list["FakeConsumer"] = []
    messages: list = []
    batch_size: int | None = None
    journal: list | None = None
    idle: asyncio.Event

    def __init__(self, topic, **config):
        self.topic = topic
        self.config = config
        self.started = self.stopped = False
        self.commits = 0
        self.seeks: list = []
        self.pending = list(self.messages)
        FakeConsumer.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def assignment(self):
        return {TopicPartition(self.topic, 0)}

    def seek(self, partition, offset):
        self.seeks.append((partition, offset))

    async def seek_to_beginning(self, *partitions):
        self.seeks.extend((p, "debut") for p in partitions)

    async def getmany(self, timeout_ms, max_records):
        if not self.pending:
            FakeConsumer.idle.set()
            await asyncio.sleep(0)  # comme un vrai consommateur sans message
            return {}
        size = min(max_records, self.batch_size or max_records)
        batch, self.pending = self.pending[:size], self.pending[size:]
        return {TopicPartition(self.topic, 0): batch}

    async def commit(self):
        self.commits += 1
        if self.journal is not None:
            self.journal.append("commit")


@pytest.fixture
def fake_consumer(monkeypatch):
    FakeConsumer.instances = []
    FakeConsumer.messages = []
    FakeConsumer.batch_size = None
    FakeConsumer.journal = None
    FakeConsumer.idle = asyncio.Event()
    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", FakeConsumer)
    return FakeConsumer


async def consume_until_idle(*args) -> None:
    """consume_topic ne rend jamais la main : annule une fois les messages
    livres et commites (le getmany suivant est vide)."""
    task = asyncio.create_task(consume_topic(*args))
    await FakeConsumer.idle.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestConsumeTopic:
    async def test_resumes_after_archived_offset(self, fake_consumer, store):
        store.insert([make_measurement(1, offset=o, timestamp_ms=NOW)
                      for o in range(5)])

        await consume_until_idle("t", {}, store, Collector())

        assert fake_consumer.instances[0].seeks == [(TopicPartition("t", 0), 5)]

    async def test_rewinds_to_beginning_without_cursor(self, fake_consumer, store):
        await consume_until_idle("t", {}, store, Collector())

        assert fake_consumer.instances[0].seeks == \
            [(TopicPartition("t", 0), "debut")]

    async def test_archive_publish_and_commit(self, fake_consumer, store):
        fake_consumer.messages = [
            make_msg(topic="t", offset=0, timestamp=NOW, value=MEASUREMENT),
            make_msg(topic="t", offset=1, timestamp=NOW + 1,
                     value=b'{"node_id": "n2", "value": 2}'),
        ]
        received = Collector()

        await consume_until_idle("t", {"group_id": "g"}, store, received)

        consumer = fake_consumer.instances[0]
        assert consumer.topic == "t"
        assert consumer.config == {"group_id": "g"}
        assert consumer.started and consumer.stopped
        assert consumer.commits == 1  # un commit par lot, aucun pour un lot vide
        assert [r["offset"] for r in received.records] == [0, 1]
        sensors = store.load(NOW, HOUR_MS, HISTORY_MS)["sensors"]
        assert sorted((s["id"], s["points"]) for s in sensors) == \
            [("n1", [[NOW, 400.0]]), ("n2", [[NOW + 1, 2.0]])]
        assert store.positions("t") == {0: 1}

    async def test_consumer_closed_when_callback_fails(self, fake_consumer, store):
        fake_consumer.messages = [make_msg(topic="t")]

        async def boom(_record):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await consume_topic("t", {}, store, boom)

        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0  # pas de commit d'un lot non traite

    async def test_store_failure_stops_consumer_without_commit(self, fake_consumer):
        fake_consumer.messages = [make_msg(topic="t")]
        received = Collector()

        class BrokenStore:
            def positions(self, topic):
                return {}

            def insert(self, records):
                raise sqlite3.OperationalError("disque plein")

        with pytest.raises(sqlite3.OperationalError):
            await consume_topic("t", {}, BrokenStore(), received)

        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0
        assert received.records == []  # archive avant notification

    async def test_commit_after_all_observers_notified(self, fake_consumer, store):
        journal = []
        fake_consumer.journal = journal
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]

        class Slow(SpyObserver):
            """Suspend : le commit doit quand meme l'attendre."""
            async def on_record(self, topic, record, *, replay):
                await asyncio.sleep(0)
                await super().on_record(topic, record, replay=replay)

        bus = RecordBus()
        bus.subscribe(SpyObserver("premier", journal))
        bus.subscribe(Slow("lent", journal))

        await consume_until_idle("t", {}, store, functools.partial(bus.publish, "t"))

        assert journal == [
            ("premier", "t", 0, False), ("lent", "t", 0, False),
            ("premier", "t", 1, False), ("lent", "t", 1, False), "commit",
        ]

    async def test_one_commit_per_batch(self, fake_consumer, store):
        journal = []
        fake_consumer.journal = journal
        fake_consumer.batch_size = 1
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]
        bus = RecordBus()
        bus.subscribe(SpyObserver("premier", journal))

        await consume_until_idle("t", {}, store, functools.partial(bus.publish, "t"))

        assert journal == [("premier", "t", 0, False), "commit",
                           ("premier", "t", 1, False), "commit"]

    async def test_cancellation_during_notification_no_commit(
            self, fake_consumer, store):
        """Pas de commit : lot relu au redemarrage (au moins une fois)."""
        fake_consumer.messages = [make_msg(topic="t", timestamp=NOW,
                                           value=MEASUREMENT)]
        en_cours = asyncio.Event()

        async def blocking(_record):
            en_cours.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(consume_topic("t", {}, store, blocking))
        await en_cours.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0
        # Le lot etait deja archive avant la notification
        assert store.positions("t") == {0: 0}

    async def test_failing_observer_blocks_neither_commit_nor_broadcast(
            self, fake_consumer, store):
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]
        hub = TopicHub()
        queue = hub.subscribe("t")
        bus = RecordBus()
        # L'observateur en panne est notifie AVANT le hub
        bus.subscribe(FailingObserver())
        bus.subscribe(hub)

        await consume_until_idle("t", {}, store, functools.partial(bus.publish, "t"))

        assert fake_consumer.instances[0].commits == 1
        assert [queue.get_nowait()["offset"] for _ in range(2)] == [0, 1]
