import asyncio

import pytest

from app.data_management.data_acquisition import history_warmup
from app.data_management.data_acquisition.history_warmup import (
    _read_tail,
    warmup_topic,
)
from tests.conftest import Collector, make_msg


class FakeConsumer:
    """Offsets [begins[p], ends[p]) par partition ; getmany() lit depuis la
    position de seek(), par lots de `batch_size`."""

    def __init__(self, topic="t", partitions=None, begins=None, ends=None,
                 start_error=None, batch_size=500):
        self.topic = topic
        self.partitions = partitions if partitions is not None else {0}
        self.begins = begins or {p: 0 for p in self.partitions}
        self.ends = ends or {p: 0 for p in self.partitions}
        self.positions: dict = {}
        self.start_error = start_error
        self.batch_size = batch_size
        self.stopped = False

    async def start(self):
        if self.start_error:
            raise self.start_error

    async def stop(self):
        self.stopped = True

    def assignment(self):
        return set(self.partitions)

    async def beginning_offsets(self, partitions):
        return {p: self.begins[p] for p in partitions}

    async def end_offsets(self, partitions):
        return {p: self.ends[p] for p in partitions}

    def seek(self, tp, offset):
        self.positions[tp] = offset

    async def getmany(self, timeout_ms, max_records):
        batches = {}
        for tp, pos in self.positions.items():
            stop = min(self.ends[tp], pos + self.batch_size)
            if pos < stop:
                batches[tp] = [make_msg(topic=self.topic, partition=tp, offset=o)
                               for o in range(pos, stop)]
                self.positions[tp] = stop
        if not batches:
            await asyncio.sleep(0)
        return batches


class TestReadTail:
    async def test_rereads_last_n_messages_per_partition(self):
        consumer = FakeConsumer(partitions={0, 1},
                                begins={0: 0, 1: 0}, ends={0: 10, 1: 3})
        published = Collector()

        await _read_tail(consumer, "t", published, tail_per_partition=4)

        by_partition = {p: sorted(r["offset"] for r in published.records
                                  if r["partition"] == p) for p in (0, 1)}
        assert by_partition[0] == [6, 7, 8, 9]
        # Partition plus courte que N : bornee par le debut
        assert by_partition[1] == [0, 1, 2]

    async def test_bounded_by_retention_start(self):
        consumer = FakeConsumer(begins={0: 8}, ends={0: 10})
        published = Collector()

        await _read_tail(consumer, "t", published, tail_per_partition=100)

        assert consumer.positions[0] == 10
        assert [r["offset"] for r in published.records] == [8, 9]

    async def test_reads_in_batches(self):
        consumer = FakeConsumer(ends={0: 10}, batch_size=3)
        published = Collector()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert [r["offset"] for r in published.records] == list(range(10))

    async def test_publish_awaited_before_next_message(self):
        consumer = FakeConsumer(ends={0: 3})
        journal = []

        async def slow_publish(record):
            journal.append(("debut", record["offset"]))
            await asyncio.sleep(0)
            journal.append(("fin", record["offset"]))

        await _read_tail(consumer, "t", slow_publish, tail_per_partition=10)

        assert journal == [("debut", 0), ("fin", 0), ("debut", 1), ("fin", 1),
                           ("debut", 2), ("fin", 2)]

    async def test_empty_topic(self):
        consumer = FakeConsumer(begins={0: 5}, ends={0: 5})
        published = Collector()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert published.records == []

    async def test_no_partition_assigned(self):
        consumer = FakeConsumer(partitions=set())
        published = Collector()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert published.records == []

    async def test_gives_up_after_timeout(self, monkeypatch):
        monkeypatch.setattr(history_warmup, "TIMEOUT_S", 0.05)

        class NeverEnding(FakeConsumer):
            async def getmany(self, timeout_ms, max_records):
                await asyncio.sleep(0.01)
                return {}

        consumer = NeverEnding(ends={0: 10})

        await asyncio.wait_for(
            _read_tail(consumer, "t", Collector(), tail_per_partition=10),
            timeout=2)


class TestWarmupTopic:
    @pytest.fixture
    def install(self, monkeypatch):
        def _install(consumer):
            monkeypatch.setattr(history_warmup, "AIOKafkaConsumer",
                                lambda topic, **config: consumer)
            return consumer
        return _install

    async def test_publishes_and_closes_consumer(self, install):
        consumer = install(FakeConsumer(ends={0: 2}))
        published = Collector()

        await warmup_topic("t", {}, published, tail_per_partition=10)

        assert [r["offset"] for r in published.records] == [0, 1]
        assert consumer.stopped

    async def test_error_logged_not_propagated(self, install, caplog):
        consumer = install(FakeConsumer(start_error=ConnectionError("broker KO")))

        await warmup_topic("t", {}, Collector(), tail_per_partition=10)

        assert consumer.stopped
        assert "echec du prechauffage" in caplog.text

    async def test_cancellation_propagated(self, install):
        consumer = install(FakeConsumer(start_error=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await warmup_topic("t", {}, Collector(), tail_per_partition=10)

        assert consumer.stopped

    async def test_cancellation_during_publish_propagated(self, install):
        """Pas confondue avec un echec du prechauffage, qui est avale."""
        consumer = install(FakeConsumer(ends={0: 2}))

        async def cancelled_publish(_record):
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await warmup_topic("t", {}, cancelled_publish, tail_per_partition=10)

        assert consumer.stopped
