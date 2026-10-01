"""Tests du consommateur Kafka (conversion des messages, archivage JSONL,
commit des offsets) avec un faux AIOKafkaConsumer."""

import json

import pytest

from app.data_management.data_acquisition import consumer as consumer_module
from app.data_management.data_acquisition.consumer import (
    consume_topic,
    record_from_msg,
)
from tests.conftest import make_msg


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
    """Imite AIOKafkaConsumer : itere sur une liste de messages fixe."""
    instances: list["FakeConsumer"] = []
    messages: list = []

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

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for msg in self.messages:
            yield msg


@pytest.fixture
def fake_consumer(monkeypatch):
    FakeConsumer.instances = []
    FakeConsumer.messages = []
    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", FakeConsumer)
    return FakeConsumer


class TestConsumeTopic:
    async def test_archive_publie_et_commite(self, fake_consumer, tmp_path):
        fake_consumer.messages = [
            make_msg(topic="t", offset=0, value=b'{"node_id": "n1"}'),
            make_msg(topic="t", offset=1, value=b'{"node_id": "n2"}'),
        ]
        received = []

        await consume_topic("t", {"group_id": "g"}, str(tmp_path / "out"),
                            received.append)

        consumer = fake_consumer.instances[0]
        assert consumer.topic == "t"
        assert consumer.config == {"group_id": "g"}
        assert consumer.started and consumer.stopped
        assert consumer.commits == 2
        assert [r["offset"] for r in received] == [0, 1]

        lines = (tmp_path / "out" / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == received

    async def test_ajoute_au_fichier_existant(self, fake_consumer, tmp_path):
        (tmp_path / "t.jsonl").write_text('{"ancien": true}\n', encoding="utf-8")
        fake_consumer.messages = [make_msg(topic="t")]

        await consume_topic("t", {}, str(tmp_path), lambda r: None)

        lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"ancien": True}

    async def test_consommateur_ferme_si_le_callback_echoue(self, fake_consumer,
                                                             tmp_path):
        fake_consumer.messages = [make_msg(topic="t")]

        def boom(_record):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await consume_topic("t", {}, str(tmp_path), boom)

        consumer = fake_consumer.instances[0]
        assert consumer.stopped
        assert consumer.commits == 0  # pas de commit d'un message non traite
