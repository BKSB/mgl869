import asyncio
import logging

import pytest

from app.data_management.record_bus import RecordBus
from tests.conftest import FailingObserver, SpyObserver, make_record


class TestSubscription:
    def test_empty_bus(self):
        assert RecordBus().observers == ()

    def test_observers_in_subscription_order(self):
        bus = RecordBus()
        a, b, c = SpyObserver("a"), SpyObserver("b"), SpyObserver("c")
        for observer in (b, a, c):
            bus.subscribe(observer)

        assert bus.observers == (b, a, c)
        # Tuple : une vue en lecture seule, pas la liste interne
        assert isinstance(bus.observers, tuple)

    def test_subscribe_idempotent(self):
        bus = RecordBus()
        espion = SpyObserver()
        bus.subscribe(espion)
        bus.subscribe(espion)

        assert bus.observers == (espion,)

    async def test_subscribe_idempotent_single_notification(self):
        bus = RecordBus()
        espion = SpyObserver()
        bus.subscribe(espion)
        bus.subscribe(espion)

        await bus.publish("t", make_record(offset=1))

        assert espion.journal == [("espion", "t", 1, False)]

    def test_equal_but_distinct_observers_both_subscribed(self):
        class AlwaysEqual(SpyObserver):
            def __eq__(self, other):
                return True

            __hash__ = None

        bus = RecordBus()
        bus.subscribe(AlwaysEqual("1"))
        bus.subscribe(AlwaysEqual("2"))

        assert len(bus.observers) == 2

    def test_unsubscribe(self):
        bus = RecordBus()
        a, b = SpyObserver("a"), SpyObserver("b")
        bus.subscribe(a)
        bus.subscribe(b)

        bus.unsubscribe(a)

        assert bus.observers == (b,)

    def test_unsubscribe_absent_without_error(self):
        bus = RecordBus()
        present = SpyObserver()
        bus.subscribe(present)

        bus.unsubscribe(SpyObserver("absent"))

        assert bus.observers == (present,)

    def test_subscription_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            RecordBus().subscribe(SpyObserver())
        assert "SpyObserver" in caplog.text


class TestPublish:
    async def test_publish_without_observer(self):
        await RecordBus().publish("t", make_record())

    async def test_notifies_in_subscription_order(self):
        journal = []
        bus = RecordBus()
        for nom in ("premier", "deuxieme", "troisieme"):
            bus.subscribe(SpyObserver(nom, journal))

        await bus.publish("t", make_record(offset=4))

        assert [entree[0] for entree in journal] == ["premier", "deuxieme", "troisieme"]
        assert all(entree[1:] == ("t", 4, False) for entree in journal)

    async def test_sequential_notification(self):
        """Un observateur qui suspend est attendu avant le suivant."""
        journal = []

        class Slow:
            async def on_record(self, topic, record, *, replay):
                journal.append("lent:debut")
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                journal.append("lent:fin")

        bus = RecordBus()
        bus.subscribe(Slow())
        bus.subscribe(SpyObserver("rapide", journal))

        await bus.publish("t", make_record(offset=0))

        assert journal == ["lent:debut", "lent:fin", ("rapide", "t", 0, False)]

    async def test_replay_false_by_default(self):
        bus = RecordBus()
        espion = SpyObserver()
        bus.subscribe(espion)

        await bus.publish("t", make_record(offset=1))
        await bus.publish("t", make_record(offset=2), replay=True)

        assert espion.journal == [("espion", "t", 1, False),
                                  ("espion", "t", 2, True)]

    async def test_record_passed_as_is(self):
        recus = []

        class Capture:
            async def on_record(self, topic, record, *, replay):
                recus.append(record)

        bus = RecordBus()
        bus.subscribe(Capture())
        record = make_record(offset=3)

        await bus.publish("t", record)

        assert recus == [record]
        assert recus[0] is record

    async def test_unsubscribe_during_notification(self):
        """Le bus itere sur une copie : aucun suivant n'est saute."""
        journal = []
        bus = RecordBus()

        class OneShot(SpyObserver):
            async def on_record(self, topic, record, *, replay):
                await super().on_record(topic, record, replay=replay)
                bus.unsubscribe(self)

        bus.subscribe(OneShot("ephemere", journal))
        bus.subscribe(SpyObserver("b", journal))
        bus.subscribe(SpyObserver("c", journal))

        await bus.publish("t", make_record(offset=0))
        await bus.publish("t", make_record(offset=1))

        assert journal == [
            ("ephemere", "t", 0, False), ("b", "t", 0, False), ("c", "t", 0, False),
            ("b", "t", 1, False), ("c", "t", 1, False),
        ]
        assert [o.nom for o in bus.observers] == ["b", "c"]

    async def test_subscribe_during_notification(self):
        """Ne recoit que les records publies apres son inscription."""
        journal = []
        bus = RecordBus()
        tardif = SpyObserver("tardif", journal)

        class Referrer(SpyObserver):
            async def on_record(self, topic, record, *, replay):
                await super().on_record(topic, record, replay=replay)
                bus.subscribe(tardif)

        bus.subscribe(Referrer("parrain", journal))

        await bus.publish("t", make_record(offset=0))
        await bus.publish("t", make_record(offset=1))

        assert journal == [
            ("parrain", "t", 0, False),
            ("parrain", "t", 1, False), ("tardif", "t", 1, False),
        ]


class TestFailureIsolation:
    async def test_failure_does_not_block_next_observers(self, caplog):
        journal = []
        bus = RecordBus()
        bus.subscribe(SpyObserver("avant", journal))
        bus.subscribe(FailingObserver())
        bus.subscribe(SpyObserver("apres", journal))

        with caplog.at_level(logging.ERROR):
            # publish ne leve pas malgre la panne
            await bus.publish("topic.x", make_record(partition=3, offset=42))

        assert [entree[0] for entree in journal] == ["avant", "apres"]

        erreurs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(erreurs) == 1
        message = erreurs[0].getMessage()
        assert "FailingObserver" in message
        assert "topic.x" in message
        assert "partition=3" in message
        assert "offset=42" in message
        # Trace de la pile conservee (logger.exception)
        assert erreurs[0].exc_info is not None
        assert "panne simulee" in caplog.text

    async def test_failure_on_every_record_does_not_stop_bus(self):
        journal = []
        bus = RecordBus()
        bus.subscribe(FailingObserver())
        bus.subscribe(SpyObserver("sain", journal))

        for offset in range(3):
            await bus.publish("t", make_record(offset=offset))

        assert [entree[2] for entree in journal] == [0, 1, 2]
        # L'observateur en panne reste inscrit
        assert len(bus.observers) == 2

    async def test_record_without_partition_or_offset_logged(self, caplog):
        bus = RecordBus()
        bus.subscribe(FailingObserver())

        with caplog.at_level(logging.ERROR):
            await bus.publish("t", {"value": "brut"})

        assert "partition=None offset=None" in caplog.text

    async def test_cancellation_propagated(self):
        journal = []

        class Cancelling:
            async def on_record(self, topic, record, *, replay):
                raise asyncio.CancelledError

        bus = RecordBus()
        bus.subscribe(Cancelling())
        bus.subscribe(SpyObserver("suivant", journal))

        with pytest.raises(asyncio.CancelledError):
            await bus.publish("t", make_record())

        # L'annulation interrompt la diffusion : rien n'est avale
        assert journal == []

    async def test_task_cancelled_during_notification(self):
        """Arret du service : l'observateur en cours est interrompu."""
        en_cours = asyncio.Event()

        class Blocking:
            async def on_record(self, topic, record, *, replay):
                en_cours.set()
                await asyncio.Event().wait()

        bus = RecordBus()
        bus.subscribe(Blocking())
        tache = asyncio.create_task(bus.publish("t", make_record()))
        await en_cours.wait()

        tache.cancel()

        with pytest.raises(asyncio.CancelledError):
            await tache
        assert tache.cancelled()
