"""Tests du service d'alertes : observateur du bus (replay : etat reconstruit
sans evenement ; idempotence par offset), alertes actives, historique
recent, abonnes WebSocket et journalisation."""

import asyncio
import logging

import pytest

from app.config import AlertsConfig
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    WARNING,
    AlertRule,
)
from app.data_management.record_bus import RecordBus
from app.services.alert_service import AlertService
from tests.conftest import make_mesure

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"


def drain(queue: asyncio.Queue) -> list[dict]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def config_alertes() -> AlertsConfig:
    return AlertsConfig(enabled=True, source="alerts.yaml", rules={
        CO2: [AlertRule(WARNING, ABOVE, 1000, 50),
              AlertRule(CRITICAL, ABOVE, 1500, 50)],
        TEMPERATURE: [AlertRule(WARNING, BELOW, 18, 0.5)],
    })


@pytest.fixture
def service():
    return AlertService(config_alertes())


class Emetteur:
    """Publie des mesures CO2 sur le service, offsets croissants par defaut."""

    def __init__(self, service: AlertService):
        self.service = service
        self.offset = 0

    async def __call__(self, valeur, ts, node_id="n1", topic=CO2, replay=False,
                       offset=None, partition=0, **kwargs):
        if offset is None:
            self.offset += 1
            offset = self.offset
        record = make_mesure(valeur, timestamp_ms=ts, offset=offset,
                             node_id=node_id, partition=partition, topic=topic,
                             **kwargs)
        await self.service.on_record(topic, record, replay=replay)
        return record


@pytest.fixture
def emettre(service):
    return Emetteur(service)


def types(service: AlertService) -> list[str]:
    """Types des evenements recents, du plus ancien au plus recent."""
    return [e["kind"] for e in reversed(service.recent())]


class TestConfiguration:
    def test_regles_exposees(self, service):
        assert service.enabled
        assert service.rules() == {
            CO2: [
                {"severity": "warning", "direction": "above",
                 "threshold": 1000.0, "hysteresis": 50.0},
                {"severity": "critical", "direction": "above",
                 "threshold": 1500.0, "hysteresis": 50.0},
            ],
            TEMPERATURE: [
                {"severity": "warning", "direction": "below",
                 "threshold": 18.0, "hysteresis": 0.5},
            ],
        }

    def test_topic_sans_regle_omis(self):
        service = AlertService(AlertsConfig(enabled=True, rules={CO2: []}))
        assert service.rules() == {}

    def test_journalise_les_regles_au_demarrage(self, caplog):
        with caplog.at_level(logging.INFO):
            AlertService(config_alertes())
        assert "3 regle(s) sur 2 topic(s)" in caplog.text

    async def test_desactive(self, caplog):
        config = config_alertes()
        config.enabled = False
        with caplog.at_level(logging.INFO):
            service = AlertService(config)

        await service.on_record(CO2, make_mesure(2000), replay=False)

        assert not service.enabled
        assert service.rules() == {}
        assert service.active() == []
        assert service.recent() == []
        assert "regle(s)" not in caplog.text
        assert drain(service.subscribe()) == [{"type": "snapshot", "active": []}]


class TestOnRecord:
    async def test_declenche_une_alerte(self, service, emettre):
        await emettre(1120, ts=100)

        (alerte,) = service.active()
        assert alerte["id"] == f"{CO2}|n1"
        assert alerte["severity"] == "warning"
        assert alerte["location"] == "Zone A"
        assert alerte["since_ms"] == 100
        assert types(service) == ["raised"]

    async def test_replay_reconstruit_l_etat_sans_evenement(self, service,
                                                            emettre):
        queue = service.subscribe()
        await emettre(1120, ts=100, replay=True)

        # L'alerte est active (debut compris) mais rien n'est historise ni
        # diffuse comme evenement : les abonnes sont re-synchronises
        (alerte,) = service.active()
        assert (alerte["severity"], alerte["since_ms"]) == ("warning", 100)
        assert service.recent() == []
        initial, resync = drain(queue)
        assert initial == {"type": "snapshot", "active": []}
        assert resync == {"type": "snapshot", "active": [alerte]}

    async def test_replay_sans_changement_de_niveau_aucun_message(
            self, service, emettre):
        queue = service.subscribe()
        await emettre(1120, ts=100, replay=True)
        await emettre(1200, ts=200, replay=True)

        assert [m["type"] for m in drain(queue)] == ["snapshot", "snapshot"]
        assert service.active()[0]["value"] == 1200

    async def test_record_rejoue_puis_consomme_evalue_une_fois(self, service,
                                                              emettre):
        record = await emettre(1120, ts=100, replay=True)
        # Le meme record lu par le consommateur (prechauffage puis reprise
        # sur offsets commites) n'est pas evalue une seconde fois
        await service.on_record(CO2, record, replay=False)

        assert service.recent() == []
        assert len(service.active()) == 1

    async def test_redemarrage_alerte_maintenue_par_l_hysteresis(
            self, service, emettre):
        """Le prechauffage rejoue la montee a 1120 puis le retour a 980,
        maintenu par l'hysteresis (1000 - 50) : a 985 en temps reel,
        l'alerte est toujours la, avec son debut d'origine."""
        await emettre(1120, ts=100, replay=True)
        await emettre(980, ts=200, replay=True)
        await emettre(985, ts=300)

        (alerte,) = service.active()
        assert (alerte["value"], alerte["since_ms"]) == (985, 100)
        assert service.recent() == []

    async def test_temps_reel_apres_replay(self, service, emettre):
        await emettre(1120, ts=100, replay=True)
        await emettre(1600, ts=200)

        assert types(service) == ["escalated"]
        assert service.recent()[0]["alert"]["since_ms"] == 100

    async def test_doublon_ignore(self, service, emettre):
        await emettre(1120, ts=100, offset=7)
        # Meme partition et offset (relecture Kafka) : ignore, meme si le
        # contenu differait
        await emettre(900, ts=100, offset=7)

        assert types(service) == ["raised"]
        assert service.active()[0]["value"] == 1120

    async def test_offset_deja_depasse_ignore(self, service, emettre):
        await emettre(1120, ts=100, offset=1)
        await emettre(1130, ts=200, offset=2)
        await emettre(900, ts=300, offset=1)

        assert types(service) == ["raised"]
        assert service.active()[0]["value"] == 1130

    async def test_offsets_par_topic_et_partition(self, service, emettre):
        await emettre(1120, ts=100, offset=7)
        await emettre(900, ts=100, offset=8)
        # Meme offset sur une autre partition, puis sur un autre topic :
        # d'autres records
        await emettre(1120, ts=100, offset=7, partition=1)
        await emettre(17, ts=100, offset=7, topic=TEMPERATURE, unit="C")

        assert types(service) == ["raised", "resolved", "raised", "raised"]

    async def test_meme_partition_l_ordre_des_offsets_fait_foi(self, service,
                                                              emettre):
        await emettre(1120, ts=200)
        # Horodatage qui recule (horloge corrigee) : mesure plus recente
        # dans la partition, evaluee
        await emettre(900, ts=100)

        assert types(service) == ["raised", "resolved"]

    async def test_horodatage_futur_ne_fige_pas_le_capteur(self, service,
                                                          emettre):
        demain = 100 + 24 * 3600 * 1000
        await emettre(1600, ts=demain)
        await emettre(400, ts=100)

        assert types(service) == ["raised", "resolved"]
        assert service.active() == []

    async def test_autre_partition_mesure_ancienne_ignoree(self, service,
                                                          emettre):
        await emettre(1120, ts=200, partition=0)
        # Capteur dont les records sont sur plusieurs partitions : une
        # mesure plus ancienne ne ramene pas l'etat en arriere
        await emettre(900, ts=100, partition=1)
        assert types(service) == ["raised"]
        assert service.active()[0]["updated_ms"] == 200

        # Plus recente, elle est evaluee
        await emettre(900, ts=300, partition=1)
        assert types(service) == ["raised", "resolved"]

    @pytest.mark.parametrize("valeur", ["1200", None, True])
    async def test_valeur_non_numerique_ignoree(self, service, emettre, valeur):
        await emettre(valeur, ts=100)
        assert service.active() == []
        assert service.recent() == []

    async def test_payload_non_json_ignore(self, service):
        record = make_mesure(1200, topic=CO2)
        record["value"] = "texte brut"
        await service.on_record(CO2, record, replay=False)
        assert service.recent() == []

    async def test_topic_sans_regle_ignore(self, service, emettre):
        await emettre(5000, ts=100, topic="gridd.obs.occupancy.count")
        assert service.active() == []
        assert service.recent() == []

    async def test_capteurs_independants(self, service, emettre):
        await emettre(1120, ts=100, node_id="n1")
        await emettre(900, ts=50, node_id="n2")
        await emettre(1600, ts=60, node_id="n2")

        assert {a["node_id"]: a["severity"] for a in service.active()} == \
            {"n1": "warning", "n2": "critical"}

    async def test_meme_capteur_sur_deux_topics(self, service, emettre):
        await emettre(1120, ts=100, node_id="n1")
        await emettre(17, ts=100, node_id="n1", topic=TEMPERATURE, unit="C")

        assert sorted(a["id"] for a in service.active()) == \
            [f"{CO2}|n1", f"{TEMPERATURE}|n1"]

    async def test_mise_a_jour_sans_evenement(self, service, emettre):
        await emettre(1120, ts=100)
        await emettre(1250, ts=200, zone="Zone B")

        (alerte,) = service.active()
        assert (alerte["value"], alerte["updated_ms"], alerte["since_ms"]) == \
            (1250, 200, 100)
        assert alerte["location"] == "Zone B"
        assert types(service) == ["raised"]

    async def test_cycle_complet(self, service, emettre):
        for ts, valeur in enumerate([1120, 1600, 1440, 940], start=1):
            await emettre(valeur, ts=ts)

        assert types(service) == ["raised", "escalated", "deescalated",
                                  "resolved"]
        assert service.active() == []
        resolu = service.recent()[0]
        assert resolu["kind"] == "resolved"
        assert resolu["alert"]["value"] == 940
        assert resolu["alert"]["since_ms"] == 1

    async def test_inscrit_sur_le_bus(self, service):
        bus = RecordBus()
        bus.subscribe(service)

        await bus.publish(CO2, make_mesure(1120, offset=1), replay=True)
        assert len(service.active()) == 1
        assert service.recent() == []
        await bus.publish(CO2, make_mesure(1600, timestamp_ms=2000, offset=2))
        assert types(service) == ["escalated"]


class TestActive:
    async def test_critical_d_abord_puis_par_anciennete(self, service, emettre):
        await emettre(1120, ts=300, node_id="w-recent")
        await emettre(1120, ts=100, node_id="w-ancien")
        await emettre(1600, ts=200, node_id="c-recent")
        await emettre(1600, ts=150, node_id="c-ancien")
        await emettre(1120, ts=100, node_id="w-ancien-bis")

        assert [a["node_id"] for a in service.active()] == [
            "c-ancien", "c-recent", "w-ancien", "w-ancien-bis", "w-recent"]

    async def test_escalade_garde_l_anciennete(self, service, emettre):
        await emettre(1120, ts=100, node_id="a")
        await emettre(1600, ts=150, node_id="b")
        await emettre(1600, ts=200, node_id="a")

        # a escalade en critical mais son alerte a commence avant celle de b
        assert [a["node_id"] for a in service.active()] == ["a", "b"]


class TestRecent:
    async def test_plus_recent_d_abord(self, service, emettre):
        await emettre(1120, ts=1, node_id="a")
        await emettre(1120, ts=2, node_id="b")

        assert [e["alert"]["node_id"] for e in service.recent()] == ["b", "a"]

    async def test_historique_borne(self, service, emettre):
        # 101 cycles declenchement / resolution : 202 evenements
        for i in range(101):
            await emettre(1120, ts=2 * i)
            await emettre(900, ts=2 * i + 1)

        recent = service.recent()
        assert len(recent) == AlertService.RECENT_SIZE == 200
        assert recent[0]["at_ms"] == 201
        assert recent[-1]["at_ms"] == 2


class TestAbonnes:
    async def test_snapshot_a_l_abonnement(self, service, emettre):
        await emettre(1120, ts=100, node_id="a")
        await emettre(1600, ts=200, node_id="b")

        (snapshot,) = drain(service.subscribe())

        assert snapshot["type"] == "snapshot"
        assert [a["node_id"] for a in snapshot["active"]] == ["b", "a"]

    async def test_evenements_diffuses_aux_abonnes(self, service, emettre):
        q1, q2 = service.subscribe(), service.subscribe()

        await emettre(1120, ts=100)

        for queue in (q1, q2):
            snapshot, message = drain(queue)
            assert snapshot == {"type": "snapshot", "active": []}
            assert message["type"] == "event"
            assert message["event"] == service.recent()[0]
            assert message["event"]["kind"] == "raised"

    async def test_aucune_diffusion_sans_evenement(self, service, emettre):
        queue = service.subscribe()
        await emettre(1120, ts=100)
        await emettre(1200, ts=200)  # meme niveau : mise a jour seule

        assert [m["type"] for m in drain(queue)] == ["snapshot", "event"]

    async def test_desabonnement(self, service, emettre):
        queue = service.subscribe()
        service.unsubscribe(queue)
        service.unsubscribe(queue)  # sans erreur s'il est deja desabonne

        await emettre(1120, ts=100)

        assert [m["type"] for m in drain(queue)] == ["snapshot"]

    async def test_file_pleine_remplacee_par_un_snapshot(self, service,
                                                        emettre):
        """Un client trop lent ne perd pas un evenement isole (sa liste
        d'alertes serait fausse) : ses messages en attente sont remplaces
        par un snapshot de l'etat courant."""
        service.CLIENT_QUEUE_SIZE = 2
        queue = service.subscribe()  # snapshot

        await emettre(1120, ts=1)    # raised : la file est pleine
        await emettre(1600, ts=2)    # escalated : debordement
        await emettre(900, ts=3)     # resolved

        snapshot, resolution = drain(queue)
        assert snapshot["type"] == "snapshot"
        assert [a["severity"] for a in snapshot["active"]] == ["critical"]
        assert resolution["event"]["kind"] == "resolved"
        # Les autres abonnes et l'historique ne sont pas affectes
        assert types(service) == ["raised", "escalated", "resolved"]

    async def test_evenements_independants_de_l_etat(self, service, emettre):
        """Un evenement deja diffuse n'est pas modifie par les mesures
        suivantes (copie, pas une reference sur l'etat courant)."""
        queue = service.subscribe()
        await emettre(1120, ts=100)
        await emettre(1250, ts=200)

        _, message = drain(queue)
        assert message["event"]["alert"]["value"] == 1120


class TestJournalisation:
    async def test_niveaux_par_type_d_evenement(self, service, emettre, caplog):
        with caplog.at_level(logging.INFO,
                             logger="app.services.alert_service"):
            for ts, valeur in enumerate([1120, 1600, 1440, 940], start=1):
                await emettre(valeur, ts=ts)

        niveaux = {r.getMessage().split("alerte ")[1].split(" ")[0]: r.levelno
                   for r in caplog.records if "alerte " in r.getMessage()}
        assert niveaux == {
            "raised": logging.WARNING,
            "escalated": logging.WARNING,
            "deescalated": logging.INFO,
            "resolved": logging.INFO,
        }

    async def test_message_avec_capteur_et_emplacement(self, service, emettre,
                                                       caplog):
        with caplog.at_level(logging.WARNING):
            await emettre(1120, ts=1, node_id="n9", zone="Zone B")
            await emettre(1120, ts=1, node_id="n10", zone=None, space=None)

        assert f"[{CO2}] alerte raised (warning) capteur n9 (Zone B)" in \
            caplog.text
        assert "capteur n10 :" in caplog.text
