"""Tests de la couche service : validation de la configuration, lancement
et arret des taches, publication sur le bus de records (prechauffage et
rattrapage rejoues, flux temps reel), supervision et etat de sante."""

import asyncio
import logging
import time

import pytest

from app.config import AlertsConfig, TopicConfig
from app.data_management.data_acquisition import consumer as consumer_module
from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    WARNING,
    AlertRule,
)
from app.data_management.record_bus import RecordBus
from app.services import streaming_service
from app.services.streaming_service import StreamingService
from tests.conftest import (
    ObservateurEnPanne,
    ObservateurEspion,
    make_msg,
    make_record,
)


def service_de(settings, hub: TopicHub | None = None) -> StreamingService:
    """Service sur un bus neuf (le service y inscrit le hub)."""
    return StreamingService(settings, hub if hub is not None else TopicHub(),
                            RecordBus())


def maintenant_ms() -> int:
    return int(time.time() * 1000)


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
        assert service_de(plaintext_settings()).validate() == []

    def test_certificat_ca_introuvable(self, plaintext_settings, tmp_path):
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(tmp_path / "absent.crt"))
        errors = service_de(settings).validate()
        assert len(errors) == 1
        assert "Certificat CA introuvable" in errors[0]

    def test_certificat_ca_present(self, plaintext_settings, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_text("cert")
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(ca))
        assert service_de(settings).validate() == []

    @pytest.mark.parametrize("username,password", [("", ""), ("u", ""), ("", "p")])
    def test_identifiants_sasl_requis(self, plaintext_settings, username, password):
        settings = plaintext_settings(security_protocol="SASL_PLAINTEXT",
                                      sasl_username=username,
                                      sasl_password=password)
        errors = service_de(settings).validate()
        assert any("KAFKA_USERNAME" in e for e in errors)

    def test_aucun_topic(self, plaintext_settings):
        errors = service_de(plaintext_settings(topic_configs=[])).validate()
        assert any("Aucun topic" in e for e in errors)

    def test_alertes_valides(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, rules={
            "topic.a": [AlertRule(WARNING, ABOVE, 1)]})
        settings = plaintext_settings(alerts=alerts)
        assert service_de(settings).validate() == []

    def test_alertes_invalides(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, source="alerts.yaml",
                              errors=["alerts.yaml : severite inconnue"])
        settings = plaintext_settings(alerts=alerts)
        errors = service_de(settings).validate()
        assert errors == ["alerts.yaml : severite inconnue"]

    def test_alerte_sur_un_topic_non_consomme(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, source="alerts.yaml", rules={
            "topic.inconnu": [AlertRule(WARNING, ABOVE, 1)]})
        settings = plaintext_settings(alerts=alerts)
        (error,) = service_de(settings).validate()
        assert "topic non consomme" in error
        assert "topic.inconnu" in error


class TestRequetes:
    def test_topics_et_topic_connu(self, plaintext_settings):
        service = service_de(plaintext_settings())
        assert service.topics() == ["topic.a", "topic.b"]
        assert service.is_known_topic("topic.a")
        assert not service.is_known_topic("inconnu")

    def test_subscribe_unsubscribe_delegues_au_hub(self, plaintext_settings):
        hub = TopicHub()
        service = service_de(plaintext_settings(), hub)
        queue = service.subscribe("topic.a")
        hub.publish("topic.a", make_record())
        assert queue.qsize() == 1

        service.unsubscribe("topic.a", queue)
        hub.publish("topic.a", make_record(offset=1))
        assert queue.qsize() == 1


class TestBusDeRecords:
    def test_le_service_inscrit_son_hub_sur_le_bus(self, plaintext_settings):
        """Les abonnements WebSocket du service dependent du hub : un bus
        sans le hub ne livrerait rien aux clients /ws/<topic>."""
        hub, bus = TopicHub(), RecordBus()
        StreamingService(plaintext_settings(), hub, bus)
        assert bus.observers == (hub,)

    def test_hub_deja_inscrit_ordre_conserve(self, plaintext_settings):
        """Le composition root choisit l'ordre : un hub deja inscrit ne
        l'est pas deux fois et garde sa place."""
        hub, espion, bus = TopicHub(), ObservateurEspion(), RecordBus()
        bus.subscribe(espion)
        bus.subscribe(hub)
        StreamingService(plaintext_settings(), hub, bus)
        assert bus.observers == (espion, hub)

    async def test_prechauffage_rejoue_consommateur_temps_reel(
            self, plaintext_settings, fake_tasks):
        # Prechauffage actif sur les deux topics : verifie aussi que chaque
        # callback reste lie a SON topic (pas de liaison tardive)
        settings = plaintext_settings(topic_configs=[
            TopicConfig("topic.a", history_per_sensor=10, warmup_messages=5),
            TopicConfig("topic.b", history_per_sensor=10, warmup_messages=5),
        ])
        espion = ObservateurEspion()
        bus = RecordBus()
        bus.subscribe(espion)
        service = StreamingService(settings, TopicHub(), bus)
        service.start()
        await asyncio.sleep(0)

        ts = maintenant_ms()
        for call in fake_tasks["warmup"]:
            await call["publish"](make_record(topic=call["topic"], offset=1,
                                              timestamp_ms=ts))
        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"], offset=2,
                                                timestamp_ms=ts))

        assert espion.journal == [
            ("espion", "topic.a", 1, True), ("espion", "topic.b", 1, True),
            ("espion", "topic.a", 2, False), ("espion", "topic.b", 2, False),
        ]
        await service.stop()

    async def test_rattrapage_anterieur_au_demarrage_rejoue(
            self, plaintext_settings, fake_tasks):
        """Records du consommateur horodates plus de BACKLOG_GRACE_MS avant
        le demarrage (arret prolonge, ou toute la retention sans offset
        commite) : rejoues ; un arret plus court reste du temps reel."""
        espion = ObservateurEspion()
        bus = RecordBus()
        bus.subscribe(espion)
        service = StreamingService(plaintext_settings(), TopicHub(), bus)
        demarrage = maintenant_ms()
        service.start()
        await asyncio.sleep(0)
        (on_record,) = [c["on_record"] for c in fake_tasks["consume"]
                        if c["topic"] == "topic.a"]

        grace = StreamingService.BACKLOG_GRACE_MS
        for offset, ts in enumerate([1000, demarrage - grace - 60_000,
                                     demarrage - grace + 60_000, demarrage]):
            await on_record(make_record(topic="topic.a", offset=offset,
                                        timestamp_ms=ts))
        # Horodatage absent : rien ne permet de le dater, il reste temps reel
        await on_record(make_record(topic="topic.a", offset=9,
                                    timestamp_ms=None))

        assert [(offset, replay) for _, _, offset, replay in espion.journal] \
            == [(0, True), (1, True), (2, False), (3, False), (9, False)]
        await service.stop()

    async def test_observateur_supplementaire_recoit_les_deux_topics(
            self, plaintext_settings, fake_tasks):
        hub, bus = TopicHub(), RecordBus()
        service = StreamingService(plaintext_settings(), hub, bus)
        espion = ObservateurEspion()
        bus.subscribe(espion)
        service.start()
        await asyncio.sleep(0)
        queue_a, queue_b = hub.subscribe("topic.a"), hub.subscribe("topic.b")

        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"], offset=3,
                                                timestamp_ms=maintenant_ms()))

        assert sorted(espion.journal) == [("espion", "topic.a", 3, False),
                                          ("espion", "topic.b", 3, False)]
        # Le hub, inscrit en premier, diffuse toujours
        assert queue_a.qsize() == 1
        assert queue_b.qsize() == 1
        await service.stop()

    async def test_panne_d_observateur_n_empeche_ni_commit_ni_diffusion(
            self, plaintext_settings, monkeypatch, caplog):
        """De bout en bout avec le VRAI consume_topic (Kafka simule) : un
        observateur en panne, inscrit avant le hub, n'empeche ni la
        diffusion WebSocket ni le commit des offsets."""
        commits: dict[str, int] = {}

        class KafkaSimule:
            """Faux AIOKafkaConsumer : livre deux messages puis s'arrete."""

            def __init__(self, topic, **config):
                self.topic = topic

            async def start(self):
                pass

            async def stop(self):
                pass

            async def commit(self):
                commits[self.topic] = commits.get(self.topic, 0) + 1

            def __aiter__(self):
                return self._iter()

            async def _iter(self):
                for offset in range(2):
                    yield make_msg(topic=self.topic, offset=offset)

        monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", KafkaSimule)
        settings = plaintext_settings(topic_configs=[
            TopicConfig("topic.a", history_per_sensor=10, warmup_messages=0),
            TopicConfig("topic.b", history_per_sensor=10, warmup_messages=0),
        ])
        hub = TopicHub()
        queues = {t: hub.subscribe(t) for t in ("topic.a", "topic.b")}
        bus = RecordBus()
        bus.subscribe(ObservateurEnPanne())
        bus.subscribe(hub)
        service = StreamingService(settings, hub, bus)

        with caplog.at_level(logging.ERROR):
            service.start()

            async def consommateurs_termines():
                while any(service.health()["consumers"].values()):
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(consommateurs_termines(), timeout=5)

        assert commits == {"topic.a": 2, "topic.b": 2}
        for queue in queues.values():
            assert [queue.get_nowait()["offset"] for _ in range(2)] == [0, 1]
        pannes = [r for r in caplog.records if "ObservateurEnPanne" in r.getMessage()]
        assert len(pannes) == 4
        await service.stop()


class TestCycleDeVie:
    async def test_start_lance_consommateurs_et_prechauffage(
            self, plaintext_settings, fake_tasks, tmp_path):
        service = service_de(plaintext_settings())
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
        service = service_de(plaintext_settings(), hub)
        service.start()
        await asyncio.sleep(0)
        queue_a, queue_b = hub.subscribe("topic.a"), hub.subscribe("topic.b")

        for call in fake_tasks["consume"]:
            await call["on_record"](make_record(topic=call["topic"]))

        assert queue_a.get_nowait()["topic"] == "topic.a"
        assert queue_b.get_nowait()["topic"] == "topic.b"
        await service.stop()

    async def test_stop_annule_les_taches(self, plaintext_settings, fake_tasks):
        service = service_de(plaintext_settings())
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
        service = service_de(plaintext_settings())
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
        service = service_de(settings)
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
