import asyncio

import pytest
from aiokafka.structs import TopicPartition

from app.data_management.data_acquisition import live_follower
from app.data_management.data_acquisition.live_follower import follow_topic
from tests.conftest import Collector, make_msg


def tp(partition: int) -> TopicPartition:
    return TopicPartition("t", partition)


class FakeConsumer:
    """Offsets [begins[p], ends[p]) par partition ; getmany() lit depuis la
    position de seek(), par lots de `batch_size` ; `ends` peut grandir en
    cours de route (nouveaux messages)."""

    def __init__(self, topic="t", partitions=None, begins=None, ends=None,
                 start_error=None, batch_size=500):
        ids = partitions if partitions is not None else {0}
        self.topic = topic
        self.partitions = {TopicPartition(topic, p) for p in ids}
        self.begins = {TopicPartition(topic, p): (begins or {}).get(p, 0) for p in ids}
        self.ends = {TopicPartition(topic, p): (ends or {}).get(p, 0) for p in ids}
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

    def seek(self, partition, offset):
        self.positions[partition] = offset

    async def getmany(self, timeout_ms, max_records):
        batches = {}
        for partition, pos in self.positions.items():
            stop = min(self.ends[partition], pos + self.batch_size)
            if pos < stop:
                batches[partition] = [
                    make_msg(topic=self.topic, partition=partition.partition,
                             offset=o) for o in range(pos, stop)]
                self.positions[partition] = stop
        if not batches:
            await asyncio.sleep(0)
        return batches


def done(_targets) -> bool:
    """Consommateur deja a jour : le suivi se termine aussitot."""
    return True


@pytest.fixture
def install(monkeypatch):
    def _install(consumer):
        monkeypatch.setattr(live_follower, "AIOKafkaConsumer",
                            lambda topic, **config: consumer)
        return consumer
    return _install


async def follow(replay=None, live=None, caught_up=done, tail=10):
    replay = Collector() if replay is None else replay
    live = Collector() if live is None else live
    await follow_topic("t", {}, replay, live, caught_up, tail_per_partition=tail)
    return replay, live


def offsets(collector: Collector, partition: int = 0) -> list[int]:
    return [r["offset"] for r in collector.records if r["partition"] == partition]


class TestTail:
    async def test_rereads_last_n_messages_per_partition(self, install):
        install(FakeConsumer(partitions={0, 1}, ends={0: 10, 1: 3}))

        replay, live = await follow(tail=4)

        assert offsets(replay, 0) == [6, 7, 8, 9]
        # Partition plus courte que N : bornee par le debut
        assert offsets(replay, 1) == [0, 1, 2]
        assert live.records == []

    async def test_bounded_by_retention_start(self, install):
        consumer = install(FakeConsumer(begins={0: 8}, ends={0: 10}))

        replay, _live = await follow(tail=100)

        assert consumer.positions[tp(0)] == 10
        assert offsets(replay) == [8, 9]

    async def test_reads_in_batches(self, install):
        install(FakeConsumer(ends={0: 10}, batch_size=3))
        replay, _live = await follow(tail=10)
        assert offsets(replay) == list(range(10))

    async def test_publish_awaited_before_next_message(self, install):
        install(FakeConsumer(ends={0: 3}))
        journal = []

        async def slow_publish(record):
            journal.append(("debut", record["offset"]))
            await asyncio.sleep(0)
            journal.append(("fin", record["offset"]))

        await follow(replay=slow_publish, tail=10)

        assert journal == [("debut", 0), ("fin", 0), ("debut", 1), ("fin", 1),
                           ("debut", 2), ("fin", 2)]

    async def test_empty_topic(self, install):
        install(FakeConsumer(begins={0: 5}, ends={0: 5}))
        replay, live = await follow(tail=10)
        assert replay.records == [] and live.records == []

    async def test_no_tail_when_zero(self, install):
        consumer = install(FakeConsumer(ends={0: 10}))

        replay, _live = await follow(tail=0)

        assert replay.records == []
        assert consumer.positions[tp(0)] == 10  # suivi depuis la fin

    async def test_no_partition_assigned(self, install):
        install(FakeConsumer(partitions=set()))
        replay, live = await follow()
        assert replay.records == [] and live.records == []

    async def test_gives_up_after_timeout(self, install, monkeypatch):
        monkeypatch.setattr(live_follower, "TIMEOUT_S", 0.05)

        class NeverEnding(FakeConsumer):
            async def getmany(self, timeout_ms, max_records):
                await asyncio.sleep(0.01)
                return {}

        install(NeverEnding(ends={0: 10}))

        await asyncio.wait_for(follow(tail=10), timeout=2)


class TestFollow:
    async def test_live_until_consumer_caught_up(self, install):
        consumer = install(FakeConsumer(ends={0: 2}))
        checks = []

        def caught_up(targets):
            checks.append(dict(targets))
            consumer.ends[tp(0)] += 1  # un nouveau message arrive
            return len(checks) == 3

        replay, live = await follow(caught_up=caught_up, tail=10)

        assert offsets(replay) == [0, 1]
        assert offsets(live) == [2, 3]
        # Cible : la fin relevee au depart, insensible aux arrivees
        assert checks == [{0: 2}] * 3
        assert consumer.stopped

    async def test_empty_partitions_not_targeted(self, install):
        install(FakeConsumer(partitions={0, 1}, begins={0: 5, 1: 0},
                             ends={0: 5, 1: 3}))
        seen = []

        def caught_up(targets):
            seen.append(dict(targets))
            return True

        await follow(caught_up=caught_up, tail=0)

        assert seen == [{1: 3}]

    async def test_error_logged_not_propagated(self, install, caplog):
        consumer = install(FakeConsumer(start_error=ConnectionError("broker KO")))

        await follow()

        assert consumer.stopped
        assert "suivi temps reel interrompu" in caplog.text

    async def test_cancellation_propagated(self, install):
        consumer = install(FakeConsumer(start_error=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await follow()

        assert consumer.stopped

    async def test_cancellation_during_publish_propagated(self, install):
        """Pas confondue avec une panne, qui est avalee."""
        consumer = install(FakeConsumer(ends={0: 2}))

        async def cancelled_publish(_record):
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await follow(replay=cancelled_publish)

        assert consumer.stopped
