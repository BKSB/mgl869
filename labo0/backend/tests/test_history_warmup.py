"""Tests du prechauffage d'historique (relecture de la fin des partitions)
avec un faux AIOKafkaConsumer."""

import asyncio

import pytest

from app.data_management.data_acquisition import history_warmup
from app.data_management.data_acquisition.history_warmup import (
    _read_tail,
    warmup_topic,
)
from tests.conftest import Collecteur, make_msg


class FakeConsumer:
    """Imite l'API AIOKafkaConsumer utilisee par le prechauffage.

    `log` : partition -> liste de (offset) disponibles entre `begin` et `end`.
    getmany() renvoie les messages a partir de la position fixee par seek()."""

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
    async def test_relit_les_n_derniers_messages_par_partition(self):
        consumer = FakeConsumer(partitions={0, 1},
                                begins={0: 0, 1: 0}, ends={0: 10, 1: 3})
        published = Collecteur()

        await _read_tail(consumer, "t", published, tail_per_partition=4)

        by_partition = {p: sorted(r["offset"] for r in published.records
                                  if r["partition"] == p) for p in (0, 1)}
        assert by_partition[0] == [6, 7, 8, 9]
        # Partition plus courte que N : bornee par le debut
        assert by_partition[1] == [0, 1, 2]

    async def test_borne_par_le_debut_de_retention(self):
        consumer = FakeConsumer(begins={0: 8}, ends={0: 10})
        published = Collecteur()

        await _read_tail(consumer, "t", published, tail_per_partition=100)

        assert consumer.positions[0] == 10
        assert [r["offset"] for r in published.records] == [8, 9]

    async def test_lecture_en_plusieurs_lots(self):
        consumer = FakeConsumer(ends={0: 10}, batch_size=3)
        published = Collecteur()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert [r["offset"] for r in published.records] == list(range(10))

    async def test_publication_attendue_avant_le_message_suivant(self):
        """`publish` est une coroutine attendue : chaque record est traite
        jusqu'au bout (meme si l'observateur suspend) avant le suivant."""
        consumer = FakeConsumer(ends={0: 3})
        journal = []

        async def publish_lent(record):
            journal.append(("debut", record["offset"]))
            await asyncio.sleep(0)
            journal.append(("fin", record["offset"]))

        await _read_tail(consumer, "t", publish_lent, tail_per_partition=10)

        assert journal == [("debut", 0), ("fin", 0), ("debut", 1), ("fin", 1),
                           ("debut", 2), ("fin", 2)]

    async def test_topic_vide(self):
        consumer = FakeConsumer(begins={0: 5}, ends={0: 5})
        published = Collecteur()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert published.records == []

    async def test_aucune_partition_assignee(self):
        consumer = FakeConsumer(partitions=set())
        published = Collecteur()

        await _read_tail(consumer, "t", published, tail_per_partition=10)

        assert published.records == []

    async def test_abandon_apres_timeout(self, monkeypatch):
        monkeypatch.setattr(history_warmup, "TIMEOUT_S", 0.05)

        class NeverEnding(FakeConsumer):
            async def getmany(self, timeout_ms, max_records):
                await asyncio.sleep(0.01)
                return {}

        consumer = NeverEnding(ends={0: 10})

        await asyncio.wait_for(
            _read_tail(consumer, "t", Collecteur(), tail_per_partition=10),
            timeout=2)


class TestWarmupTopic:
    @pytest.fixture
    def install(self, monkeypatch):
        def _install(consumer):
            monkeypatch.setattr(history_warmup, "AIOKafkaConsumer",
                                lambda topic, **config: consumer)
            return consumer
        return _install

    async def test_publie_et_ferme_le_consommateur(self, install):
        consumer = install(FakeConsumer(ends={0: 2}))
        published = Collecteur()

        await warmup_topic("t", {}, published, tail_per_partition=10)

        assert [r["offset"] for r in published.records] == [0, 1]
        assert consumer.stopped

    async def test_erreur_journalisee_sans_propagation(self, install, caplog):
        consumer = install(FakeConsumer(start_error=ConnectionError("broker KO")))

        await warmup_topic("t", {}, Collecteur(), tail_per_partition=10)

        assert consumer.stopped
        assert "echec du prechauffage" in caplog.text

    async def test_annulation_propagee(self, install):
        consumer = install(FakeConsumer(start_error=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await warmup_topic("t", {}, Collecteur(), tail_per_partition=10)

        assert consumer.stopped

    async def test_annulation_pendant_la_publication_propagee(self, install):
        """Arret du service pendant que le bus notifie ses observateurs :
        l'annulation n'est pas confondue avec un echec du prechauffage."""
        consumer = install(FakeConsumer(ends={0: 2}))

        async def publish_annule(_record):
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await warmup_topic("t", {}, publish_annule, tail_per_partition=10)

        assert consumer.stopped
