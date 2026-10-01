"""Tests de la couche service : validation de la configuration, lancement
et arret des taches, supervision et etat de sante."""

import asyncio
import logging

import pytest

from app.config import TopicConfig
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.services import streaming_service
from app.services.streaming_service import StreamingService
from tests.conftest import make_record


@pytest.fixture
def fake_tasks(monkeypatch):
    """Remplace consume_topic / warmup_topic par des coroutines qui
    enregistrent leurs arguments puis attendent l'annulation."""
    calls = {"consume": [], "warmup": []}

    async def fake_consume(**kwargs):
        calls["consume"].append(kwargs)
        await asyncio.Event().wait()

    async def fake_warmup(**kwargs):
        calls["warmup"].append(kwargs)

    monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
    monkeypatch.setattr(streaming_service, "warmup_topic", fake_warmup)
    return calls


class TestValidate:
    def test_configuration_valide(self, plaintext_settings):
        assert StreamingService(plaintext_settings(), TopicHub()).validate() == []

    def test_certificat_ca_introuvable(self, plaintext_settings, tmp_path):
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(tmp_path / "absent.crt"))
        errors = StreamingService(settings, TopicHub()).validate()
        assert len(errors) == 1
        assert "Certificat CA introuvable" in errors[0]

    def test_certificat_ca_present(self, plaintext_settings, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_text("cert")
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(ca))
        assert StreamingService(settings, TopicHub()).validate() == []

    @pytest.mark.parametrize("username,password", [("", ""), ("u", ""), ("", "p")])
    def test_identifiants_sasl_requis(self, plaintext_settings, username, password):
        settings = plaintext_settings(security_protocol="SASL_PLAINTEXT",
                                      sasl_username=username,
                                      sasl_password=password)
        errors = StreamingService(settings, TopicHub()).validate()
        assert any("KAFKA_USERNAME" in e for e in errors)

    def test_aucun_topic(self, plaintext_settings):
        errors = StreamingService(plaintext_settings(topic_configs=[]),
                                  TopicHub()).validate()
        assert any("Aucun topic" in e for e in errors)


class TestRequetes:
    def test_topics_et_topic_connu(self, plaintext_settings):
        service = StreamingService(plaintext_settings(), TopicHub())
        assert service.topics() == ["topic.a", "topic.b"]
        assert service.is_known_topic("topic.a")
        assert not service.is_known_topic("inconnu")

    def test_subscribe_unsubscribe_delegues_au_hub(self, plaintext_settings):
        hub = TopicHub()
        service = StreamingService(plaintext_settings(), hub)
        queue = service.subscribe("topic.a")
        hub.publish("topic.a", make_record())
        assert queue.qsize() == 1

        service.unsubscribe("topic.a", queue)
        hub.publish("topic.a", make_record(offset=1))
        assert queue.qsize() == 1


class TestCycleDeVie:
    async def test_start_lance_consommateurs_et_prechauffage(
            self, plaintext_settings, fake_tasks, tmp_path):
        service = StreamingService(plaintext_settings(), TopicHub())
        service.start()
        await asyncio.sleep(0)

        consumed = {c["topic"]: c for c in fake_tasks["consume"]}
        assert set(consumed) == {"topic.a", "topic.b"}
        assert consumed["topic.a"]["output_dir"] == str(tmp_path)
        assert consumed["topic.a"]["consumer_config"]["group_id"].endswith(".topic.a")

        # topic.b a warmup_messages=0 : pas de prechauffage
        assert [w["topic"] for w in fake_tasks["warmup"]] == ["topic.a"]
        warmup = fake_tasks["warmup"][0]
        assert warmup["tail_per_partition"] == 5
        assert warmup["consumer_config"]["group_id"] is None

        assert service.health() == {
            "status": "ok",
            "consumers": {"topic.a": True, "topic.b": True},
        }
        await service.stop()

    async def test_publication_routee_vers_le_bon_topic(
            self, plaintext_settings, fake_tasks):
        hub = TopicHub()
        service = StreamingService(plaintext_settings(), hub)
        service.start()
        await asyncio.sleep(0)
        queue_a, queue_b = hub.subscribe("topic.a"), hub.subscribe("topic.b")

        for call in fake_tasks["consume"]:
            call["on_record"](make_record(topic=call["topic"]))

        assert queue_a.get_nowait()["topic"] == "topic.a"
        assert queue_b.get_nowait()["topic"] == "topic.b"
        await service.stop()

    async def test_stop_annule_les_taches(self, plaintext_settings, fake_tasks):
        service = StreamingService(plaintext_settings(), TopicHub())
        service.start()
        await asyncio.sleep(0)

        await service.stop()

        assert all(not alive for alive in service.health()["consumers"].values())
        assert service.health()["status"] == "degraded"

    async def test_sante_degradee_si_un_consommateur_tombe(
            self, plaintext_settings, monkeypatch):
        async def fake_consume(**kwargs):
            if kwargs["topic"] == "topic.b":
                raise RuntimeError("broker KO")
            await asyncio.Event().wait()

        async def fake_warmup(**kwargs):
            pass

        monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
        monkeypatch.setattr(streaming_service, "warmup_topic", fake_warmup)
        service = StreamingService(plaintext_settings(), TopicHub())
        service.start()
        await asyncio.sleep(0)

        assert service.health() == {
            "status": "degraded",
            "consumers": {"topic.a": True, "topic.b": False},
        }
        await service.stop()

    async def test_watch_consumers_signale_une_seule_fois(
            self, plaintext_settings, monkeypatch, caplog):
        async def fake_consume(**kwargs):
            raise RuntimeError("broker KO")

        monkeypatch.setattr(streaming_service, "consume_topic", fake_consume)
        settings = plaintext_settings(
            topic_configs=[TopicConfig("topic.a", 10, 0)])
        service = StreamingService(settings, TopicHub())
        service.start()
        await asyncio.sleep(0)

        real_sleep = asyncio.sleep
        ticks = 0

        async def fast_sleep(_delay):
            nonlocal ticks
            ticks += 1
            if ticks > 3:
                raise asyncio.CancelledError
            await real_sleep(0)

        monkeypatch.setattr(streaming_service.asyncio, "sleep", fast_sleep)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(asyncio.CancelledError):
                await service.watch_consumers()
        monkeypatch.undo()

        errors = [r for r in caplog.records
                  if "Consommateur arrete inopinement" in r.getMessage()]
        assert len(errors) == 1
        assert "topic.a" in errors[0].getMessage()
        assert "broker KO" in errors[0].getMessage()
        await service.stop()
