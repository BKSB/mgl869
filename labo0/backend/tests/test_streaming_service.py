import asyncio
import logging
import time

import pytest
from aiokafka.structs import TopicPartition

from app.config import TopicConfig
from app.data_management.data_acquisition import consumer as consumer_module
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from app.services import streaming_service
from app.services.streaming_service import StreamingService
from tests.conftest import (
    FailingObserver,
    SpyObserver,
    make_msg,
    make_record,
)


class FakeStore:
    """Archive factice : lots recus, aucun curseur."""

    def __init__(self):
        self.batches: list[list[dict]] = []

    def positions(self, topic):
        return {}

    def insert(self, records):
        self.batches.append(list(records))
        return len(records)


def bus_with(*observateurs) -> RecordBus:
    bus = RecordBus()
    for observateur in observateurs:
        bus.subscribe(observateur)
    return bus


def make_service(settings, hub: TopicHub | None = None,
                 store: FakeStore | None = None) -> StreamingService:
    """Service sur un bus neuf ou seul le hub est inscrit."""
    hub = hub if hub is not None else TopicHub()
    return StreamingService(settings, hub, bus_with(hub),
                            store if store is not None else FakeStore())


def now_ms() -> int:
    return int(time.time() * 1000)


@pytest.fixture
def fake_tasks(monkeypatch):
    """Faux consume_topic / follow_topic qui enregistrent leurs arguments
    puis attendent l'annulation."""
    calls = {"consume": [], "follow": []}

    async def fake_consume(**kwargs):
        calls["consume"].append(kwargs)
        await asyncio.Event().wait()

    async def fake_follow(**kwargs):
        calls["follow"].append(kwargs)
        await asyncio.Event().wait()

    monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
    monkeypatch.setattr(streaming_service, "follow_topic", fake_follow)
    return calls


class TestQueries:
    def test_topics_and_known_topic(self, plaintext_settings):
        service = make_service(plaintext_settings())
        assert service.topics() == ["topic.a", "topic.b"]
        assert service.is_known_topic("topic.a")
        assert not service.is_known_topic("inconnu")

    def test_subscribe_unsubscribe_delegated_to_hub(self, plaintext_settings):
        hub = TopicHub()
        service = make_service(plaintext_settings(), hub)
        queue = service.subscribe("topic.a")
        hub.publish("topic.a", make_record())
        assert queue.qsize() == 1

        service.unsubscribe("topic.a", queue)
        hub.publish("topic.a", make_record(offset=1))
        assert queue.qsize() == 1


class TestRecordBus:
    def test_bus_without_hub_rejected(self, plaintext_settings):
        """Sans le hub, le bus ne livrerait rien aux clients /ws/<topic>."""
        with pytest.raises(ValueError, match="hub"):
            StreamingService(plaintext_settings(), TopicHub(),
                             bus_with(SpyObserver()), FakeStore())

    def test_composition_root_order_kept(self, plaintext_settings):
        """Le service n'inscrit rien lui-meme."""
        hub, espion = TopicHub(), SpyObserver()
        bus = bus_with(espion, hub)
        StreamingService(plaintext_settings(), hub, bus, FakeStore())
        assert bus.observers == (espion, hub)

    async def test_tail_replayed_consumer_and_follower_live(
            self, plaintext_settings, fake_tasks):
        # Chaque callback est lie a SON topic
        settings = plaintext_settings(topic_configs=[
            TopicConfig("topic.a", history_per_sensor=10, warmup_messages=5),
            TopicConfig("topic.b", history_per_sensor=10, warmup_messages=5),
        ])
        hub, espion = TopicHub(), SpyObserver()
        service = StreamingService(settings, hub, bus_with(hub, espion), FakeStore())
        service.start()
        await asyncio.sleep(0)

        ts = now_ms()
        for call in fake_tasks["follow"]:
            await call["publish_replay"](make_record(topic=call["topic"], offset=1,
                                                     timestamp_ms=ts))
        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"], offset=2,
                                                timestamp_ms=ts))
        for call in fake_tasks["follow"]:
            await call["publish_live"](make_record(topic=call["topic"], offset=3,
                                                   timestamp_ms=ts))

        assert espion.journal == [
            ("espion", "topic.a", 1, True), ("espion", "topic.b", 1, True),
            ("espion", "topic.a", 2, False), ("espion", "topic.b", 2, False),
            ("espion", "topic.a", 3, False), ("espion", "topic.b", 3, False),
        ]
        await service.stop()

    async def test_backlog_before_startup_replayed(
            self, plaintext_settings, fake_tasks):
        """Plus de BACKLOG_GRACE_MS avant le demarrage (arret prolonge, base
        vide) : rejoue ; un arret plus court reste du temps reel."""
        hub, espion = TopicHub(), SpyObserver()
        service = StreamingService(plaintext_settings(), hub,
                                   bus_with(hub, espion), FakeStore())
        demarrage = now_ms()
        service.start()
        await asyncio.sleep(0)
        (on_record,) = [c["on_record"] for c in fake_tasks["consume"]
                        if c["topic"] == "topic.a"]

        grace = StreamingService.BACKLOG_GRACE_MS
        for offset, ts in enumerate([1000, demarrage - grace - 60_000,
                                     demarrage - grace + 60_000, demarrage]):
            await on_record(make_record(topic="topic.a", offset=offset,
                                        timestamp_ms=ts))
        # Sans horodatage : impossible a dater, reste temps reel
        await on_record(make_record(topic="topic.a", offset=9,
                                    timestamp_ms=None))

        assert [(offset, replay) for _, _, offset, replay in espion.journal] \
            == [(0, True), (1, True), (2, False), (3, False), (9, False)]
        await service.stop()

    async def test_follower_stops_when_consumer_caught_up(
            self, plaintext_settings, fake_tasks):
        service = make_service(plaintext_settings())
        service.start()
        await asyncio.sleep(0)
        follow = {c["topic"]: c for c in fake_tasks["follow"]}["topic.a"]
        consume = {c["topic"]: c for c in fake_tasks["consume"]}["topic.a"]
        caught_up = follow["caught_up"]

        assert caught_up({})  # rien a rattraper
        assert not caught_up({0: 3})
        # Ce que le suiveur publie lui-meme ne compte pas
        await follow["publish_live"](make_record(topic="topic.a", offset=5))
        assert not caught_up({0: 3})
        await consume["on_record"](make_record(topic="topic.a", offset=1))
        assert not caught_up({0: 3})
        await consume["on_record"](make_record(topic="topic.a", offset=2))
        assert caught_up({0: 3})
        assert not caught_up({0: 3, 1: 1})  # autre partition pas encore atteinte
        await service.stop()

    async def test_extra_observer_receives_both_topics(
            self, plaintext_settings, fake_tasks):
        hub = TopicHub()
        bus = bus_with(hub)
        service = StreamingService(plaintext_settings(), hub, bus, FakeStore())
        espion = SpyObserver()
        bus.subscribe(espion)
        service.start()
        await asyncio.sleep(0)
        queue_a, queue_b = hub.subscribe("topic.a"), hub.subscribe("topic.b")

        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"], offset=3,
                                                timestamp_ms=now_ms()))

        assert sorted(espion.journal) == [("espion", "topic.a", 3, False),
                                          ("espion", "topic.b", 3, False)]
        # Le hub, inscrit en premier, diffuse toujours
        assert queue_a.qsize() == 1
        assert queue_b.qsize() == 1
        await service.stop()

    async def test_failing_observer_blocks_neither_commit_nor_broadcast(
            self, plaintext_settings, monkeypatch, caplog):
        """De bout en bout avec le vrai consume_topic (Kafka simule)."""
        commits: dict[str, int] = {}

        class FakeConsumer:
            """Livre un message par appel, deux en tout, puis plus rien."""

            def __init__(self, topic, **config):
                self.topic = topic
                self.offsets = iter(range(2))

            async def start(self):
                pass

            async def stop(self):
                pass

            def assignment(self):
                return {TopicPartition(self.topic, 0)}

            async def seek_to_beginning(self, *partitions):
                pass

            async def getmany(self, timeout_ms, max_records):
                offset = next(self.offsets, None)
                if offset is None:
                    await asyncio.sleep(0.001)
                    return {}
                return {TopicPartition(self.topic, 0):
                        [make_msg(topic=self.topic, offset=offset)]}

            async def commit(self):
                commits[self.topic] = commits.get(self.topic, 0) + 1

        async def fake_follow(**kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", FakeConsumer)
        monkeypatch.setattr(streaming_service, "follow_topic", fake_follow)
        hub = TopicHub()
        queues = {t: hub.subscribe(t) for t in ("topic.a", "topic.b")}
        store = FakeStore()
        service = StreamingService(plaintext_settings(), hub,
                                   bus_with(FailingObserver(), hub), store)

        with caplog.at_level(logging.ERROR):
            service.start()

            async def all_committed():
                while commits != {"topic.a": 2, "topic.b": 2}:
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(all_committed(), timeout=5)

        for queue in queues.values():
            assert [queue.get_nowait()["offset"] for _ in range(2)] == [0, 1]
        assert len(store.batches) == 4
        pannes = [r for r in caplog.records if "FailingObserver" in r.getMessage()]
        assert len(pannes) == 4
        assert service.health()["status"] == "ok"
        await service.stop()


class TestLifecycle:
    async def test_start_launches_consumers_and_followers(
            self, plaintext_settings, fake_tasks):
        store = FakeStore()
        service = make_service(plaintext_settings(), store=store)
        service.start()
        await asyncio.sleep(0)

        consumed = {c["topic"]: c for c in fake_tasks["consume"]}
        assert set(consumed) == {"topic.a", "topic.b"}
        assert consumed["topic.a"]["store"] is store
        assert consumed["topic.a"]["consumer_config"]["group_id"].endswith(".topic.a")

        # Un suiveur par topic ; sa queue vaut warmup_messages (0 : aucune)
        followers = {f["topic"]: f for f in fake_tasks["follow"]}
        assert {t: f["tail_per_partition"] for t, f in followers.items()} == \
            {"topic.a": 5, "topic.b": 0}
        assert followers["topic.a"]["consumer_config"]["group_id"] is None

        assert service.health() == {
            "status": "ok",
            "consumers": {"topic.a": True, "topic.b": True},
        }
        await service.stop()

    async def test_publish_routed_to_right_topic(
            self, plaintext_settings, fake_tasks):
        hub = TopicHub()
        service = make_service(plaintext_settings(), hub)
        service.start()
        await asyncio.sleep(0)
        queue_a, queue_b = hub.subscribe("topic.a"), hub.subscribe("topic.b")

        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"]))

        assert queue_a.get_nowait()["topic"] == "topic.a"
        assert queue_b.get_nowait()["topic"] == "topic.b"
        await service.stop()

    async def test_stop_cancels_tasks(self, plaintext_settings, fake_tasks):
        service = make_service(plaintext_settings())
        service.start()
        await asyncio.sleep(0)

        await service.stop()

        assert all(not alive for alive in service.health()["consumers"].values())
        assert service.health()["status"] == "degraded"

    async def test_health_degraded_when_consumer_dies(
            self, plaintext_settings, monkeypatch):
        async def fake_consume(**kwargs):
            if kwargs["topic"] == "topic.b":
                raise RuntimeError("broker KO")
            await asyncio.Event().wait()

        async def fake_follow(**kwargs):
            pass

        monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
        monkeypatch.setattr(streaming_service, "follow_topic", fake_follow)
        service = make_service(plaintext_settings())
        service.start()
        await asyncio.sleep(0)

        assert service.health() == {
            "status": "degraded",
            "consumers": {"topic.a": True, "topic.b": False},
        }
        await service.stop()

    async def test_stopped_consumer_reported_once_on_exit(
            self, plaintext_settings, monkeypatch, caplog):
        async def fake_consume(**kwargs):
            raise RuntimeError("broker KO")

        async def fake_follow(**kwargs):
            pass

        monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
        monkeypatch.setattr(streaming_service, "follow_topic", fake_follow)
        settings = plaintext_settings(
            topic_configs=[TopicConfig("topic.a", 10, 0)])
        service = make_service(settings)
        with caplog.at_level(logging.ERROR):
            service.start()
            # Fin de la tache, puis execution de son callback
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        errors = [r for r in caplog.records
                  if "Consommateur arrete inopinement" in r.getMessage()]
        assert len(errors) == 1
        assert "topic.a" in errors[0].getMessage()
        assert "broker KO" in errors[0].getMessage()
        await service.stop()

    async def test_service_stop_not_reported(self, plaintext_settings,
                                             fake_tasks, caplog):
        service = make_service(plaintext_settings())
        service.start()
        await asyncio.sleep(0)

        with caplog.at_level(logging.ERROR):
            await service.stop()

        assert "arrete inopinement" not in caplog.text
