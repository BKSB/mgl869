"""Tests du consommateur Kafka (conversion des messages, archivage JSONL,
notification du bus de records puis commit des offsets) avec un faux
AIOKafkaConsumer."""

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
    Collecteur,
    ObservateurEnPanne,
    ObservateurEspion,
    make_msg,
)


class TestRecordFromMsg:
    def test_message_json(self):
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

    def test_message_non_json_conserve_tel_quel(self):
        record = record_from_msg(make_msg(value=b"pas du json"))
        assert record["value"] == "pas du json"

    def test_valeur_et_cle_absentes(self):
        record = record_from_msg(make_msg(key=None, value=None))
        assert record["key"] is None
        assert record["value"] is None

    def test_utf8_invalide_remplace(self):
        record = record_from_msg(make_msg(key=b"\xff", value=b"\xff"))
        assert record["key"] == "�"
        assert record["value"] == "�"


class FakeConsumer:
    """Imite AIOKafkaConsumer : itere sur une liste de messages fixe.
    `journal` (optionnel, partage avec des observateurs) recoit "commit" a
    chaque commit, pour verifier l'ordre notification / commit."""
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
    async def test_archive_publie_et_commite(self, fake_consumer, tmp_path):
        fake_consumer.messages = [
            make_msg(topic="t", offset=0, value=b'{"node_id": "n1"}'),
            make_msg(topic="t", offset=1, value=b'{"node_id": "n2"}'),
        ]
        received = Collecteur()

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

    async def test_ajoute_au_fichier_existant(self, fake_consumer, tmp_path):
        (tmp_path / "t.jsonl").write_text('{"ancien": true}\n', encoding="utf-8")
        fake_consumer.messages = [make_msg(topic="t")]

        await consume_topic("t", {}, str(tmp_path), Collecteur())

        lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"ancien": True}

    async def test_consommateur_ferme_si_le_callback_echoue(self, fake_consumer,
                                                             tmp_path):
        fake_consumer.messages = [make_msg(topic="t")]

        async def boom(_record):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await consume_topic("t", {}, str(tmp_path), boom)

        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0  # pas de commit d'un message non traite

    async def test_commit_apres_notification_de_tous_les_observateurs(
            self, fake_consumer, tmp_path):
        journal = []
        fake_consumer.journal = journal
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]

        class Lent(ObservateurEspion):
            """Suspend son traitement : le commit doit quand meme l'attendre."""
            async def on_record(self, topic, record, *, replay):
                await asyncio.sleep(0)
                await super().on_record(topic, record, replay=replay)

        bus = RecordBus()
        bus.subscribe(ObservateurEspion("premier", journal))
        bus.subscribe(Lent("lent", journal))

        await consume_topic("t", {}, str(tmp_path),
                            functools.partial(bus.publish, "t"))

        assert journal == [
            ("premier", "t", 0, False), ("lent", "t", 0, False), "commit",
            ("premier", "t", 1, False), ("lent", "t", 1, False), "commit",
        ]

    async def test_annulation_pendant_la_notification_sans_commit(
            self, fake_consumer, tmp_path):
        """Arret du service pendant la notification : l'offset n'est pas
        commite, le message sera relu au redemarrage (au moins une fois)."""
        fake_consumer.messages = [make_msg(topic="t")]
        en_cours = asyncio.Event()

        async def bloquant(_record):
            en_cours.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            consume_topic("t", {}, str(tmp_path), bloquant))
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

    async def test_panne_d_observateur_n_empeche_ni_commit_ni_diffusion(
            self, fake_consumer, tmp_path):
        fake_consumer.messages = [make_msg(topic="t", offset=0),
                                  make_msg(topic="t", offset=1)]
        hub = TopicHub()
        queue = hub.subscribe("t")
        bus = RecordBus()
        # L'observateur en panne est notifie AVANT le hub
        bus.subscribe(ObservateurEnPanne())
        bus.subscribe(hub)

        await consume_topic("t", {}, str(tmp_path),
                            functools.partial(bus.publish, "t"))

        assert fake_consumer.instances[0].commits == 2
        assert [queue.get_nowait()["offset"] for _ in range(2)] == [0, 1]
