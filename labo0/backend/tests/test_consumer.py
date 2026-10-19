import asyncio
import functools
import json

import pytest

from app.data_management.data_acquisition import consumer as consumer_module
from app.data_management.data_acquisition.consumer import (
    consume_topic,
    record_from_msg,
)
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from tests.conftest import (
    Collector,
    FailingObserver,
    SpyObserver,
    make_msg,
)


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
    """Itere sur `messages`. `journal`, partage avec des observateurs, recoit
    "commit" a chaque commit : ordre notification / commit."""
    instances: list["FakeConsumer"] = []
    messages: list = []
    journal: list | None = None

    def __init__(self, topic, **config):
        self.topic = topic
        self.config = config
        self.started = self.stopped = False
        self.commits = 0
        FakeConsumer.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def commit(self):
        self.commits += 1
        if self.journal is not None:
            self.journal.append("commit")

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for msg in self.messages:
            yield msg


@pytest.fixture
def fake_consumer(monkeypatch):
    FakeConsumer.instances = []
    FakeConsumer.messages = []
    FakeConsumer.journal = None
    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", FakeConsumer)
    return FakeConsumer


class TestConsumeTopic:
    async def test_archive_publish_and_commit(self, fake_consumer, tmp_path):
        fake_consumer.messages = [
            make_msg(topic="t", offset=0, value=b'{"node_id": "n1"}'),
            make_msg(topic="t", offset=1, value=b'{"node_id": "n2"}'),
        ]
        received = Collector()

        await consume_topic("t", {"group_id": "g"}, str(tmp_path / "out"),
                            received)

        consumer = fake_consumer.instances[0]
        assert consumer.topic == "t"
        assert consumer.config == {"group_id": "g"}
        assert consumer.started and consumer.stopped
        assert consumer.commits == 2
        assert [r["offset"] for r in received.records] == [0, 1]

        lines = (tmp_path / "out" / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == received.records

    async def test_appends_to_existing_file(self, fake_consumer, tmp_path):
        (tmp_path / "t.jsonl").write_text('{"ancien": true}\n', encoding="utf-8")
        fake_consumer.messages = [make_msg(topic="t")]

        await consume_topic("t", {}, str(tmp_path), Collector())

        lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"ancien": True}

    async def test_consumer_closed_when_callback_fails(self, fake_consumer,
                                                             tmp_path):
        fake_consumer.messages = [make_msg(topic="t")]

        async def boom(_record):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await consume_topic("t", {}, str(tmp_path), boom)

        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0  # pas de commit d'un message non traite

    async def test_commit_after_all_observers_notified(
            self, fake_consumer, tmp_path):
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

        await consume_topic("t", {}, str(tmp_path),
                            functools.partial(bus.publish, "t"))

        assert journal == [
            ("premier", "t", 0, False), ("lent", "t", 0, False), "commit",
            ("premier", "t", 1, False), ("lent", "t", 1, False), "commit",
        ]

    async def test_cancellation_during_notification_no_commit(
            self, fake_consumer, tmp_path):
        """Pas de commit : message relu au redemarrage (au moins une fois)."""
        fake_consumer.messages = [make_msg(topic="t")]
        en_cours = asyncio.Event()

        async def blocking(_record):
            en_cours.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            consume_topic("t", {}, str(tmp_path), blocking))
        await en_cours.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0
        # Le message etait deja archive avant la notification
        lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

    async def test_failing_observer_blocks_neither_commit_nor_broadcast(
            self, fake_consumer, tmp_path):
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]
        hub = TopicHub()
        queue = hub.subscribe("t")
        bus = RecordBus()
        # L'observateur en panne est notifie AVANT le hub
        bus.subscribe(FailingObserver())
        bus.subscribe(hub)

        await consume_topic("t", {}, str(tmp_path),
                            functools.partial(bus.publish, "t"))

        assert fake_consumer.instances[0].commits == 2
        assert [queue.get_nowait()["offset"] for _ in range(2)] == [0, 1]
