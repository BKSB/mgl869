"""Tests du hub de diffusion WebSocket (historique par capteur, rejeu,
deduplication, clients lents) et de son role d'observateur du bus de
records."""

import asyncio

from app.data_management.data_distribution.websocket_hub import TopicHub
from app.data_management.record_bus import RecordBus
from tests.conftest import make_record


def drain(queue: asyncio.Queue) -> list[dict]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def avec_capteur(record: dict, sensor: str = "n1") -> dict:
    """Record tel que diffuse par le hub : copie avec son sensor_id."""
    return {**record, "sensor_id": sensor}


class TestIdentificationDuCapteur:
    def test_historique_par_capteur_selon_l_identifiant_partage(self):
        """Le hub regroupe par l'identifiant de app.data_management.records
        (node_id, sinon cle Kafka), le meme que le service d'alertes."""
        hub = TopicHub(history_per_sensor={"t": 1})
        hub.publish("t", make_record(node_id=None, key="k1", offset=0))
        hub.publish("t", make_record(node_id="k1", offset=1))
        hub.publish("t", make_record(node_id="n2", offset=2))

        assert sorted(r["offset"] for r in drain(hub.subscribe("t"))) == [1, 2]

    def test_records_diffuses_avec_l_identifiant_du_capteur(self):
        """Les clients recoivent l'identifiant calcule par le backend : ils
        n'ont pas a redefinir l'identite d'un capteur (alertes comprises)."""
        hub = TopicHub()
        queue = hub.subscribe("t")
        sans_id = make_record(node_id=None, key=None, offset=0)
        par_cle = make_record(node_id=None, key="k1", offset=1)
        vide = make_record(node_id="", key="k2", offset=2)

        for record in (sans_id, par_cle, vide):
            hub.publish("t", record)

        assert [r["sensor_id"] for r in drain(queue)] == \
            ["_sans_node_id", "k1", "k2"]
        # Le record partage avec les autres observateurs n'est pas modifie
        assert "sensor_id" not in sans_id


class TestSubscribe:
    def test_topic_sans_historique(self):
        queue = TopicHub().subscribe("t")
        assert queue.empty()

    def test_rejeu_fusionne_par_ordre_chronologique(self):
        hub = TopicHub()
        hub.publish("t", make_record("a", offset=0, timestamp_ms=300))
        hub.publish("t", make_record("b", offset=1, timestamp_ms=100))
        hub.publish("t", make_record("a", offset=2, timestamp_ms=200))

        replay = drain(hub.subscribe("t"))

        assert [r["timestamp_ms"] for r in replay] == [100, 200, 300]

    def test_rejeu_limite_au_topic_demande(self):
        hub = TopicHub()
        hub.publish("t1", make_record(offset=0))
        hub.publish("t2", make_record(offset=1))

        replay = drain(hub.subscribe("t1"))

        assert [r["offset"] for r in replay] == [0]

    def test_file_dimensionnee_pour_rejeu_plus_marge(self):
        hub = TopicHub()
        for i in range(3):
            hub.publish("t", make_record(offset=i))
        queue = hub.subscribe("t")
        assert queue.maxsize == 3 + TopicHub.CLIENT_QUEUE_MARGIN


class TestPublish:
    def test_diffuse_aux_abonnes_du_topic_seulement(self):
        hub = TopicHub()
        q1, q2 = hub.subscribe("t"), hub.subscribe("t")
        other = hub.subscribe("autre")

        record = make_record(offset=7)
        hub.publish("t", record)

        assert drain(q1) == [avec_capteur(record)]
        assert drain(q2) == [avec_capteur(record)]
        assert drain(other) == []

    def test_desabonnement(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.unsubscribe("t", queue)

        hub.publish("t", make_record())

        assert queue.empty()

    def test_desabonnement_topic_inconnu_sans_erreur(self):
        TopicHub().unsubscribe("inconnu", asyncio.Queue())

    def test_deduplication_partition_offset(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=0, offset=5))
        hub.publish("t", make_record(partition=1, offset=5))

        assert len(drain(queue)) == 2
        assert len(drain(hub.subscribe("t"))) == 2

    def test_historique_borne_par_capteur(self):
        hub = TopicHub(history_per_sensor={"t": 2})
        for i in range(5):
            hub.publish("t", make_record("bavard", offset=i, timestamp_ms=i))
        hub.publish("t", make_record("lent", offset=100, timestamp_ms=0))

        replay = drain(hub.subscribe("t"))

        bavard = [r["offset"] for r in replay if r["value"]["node_id"] == "bavard"]
        lent = [r["offset"] for r in replay if r["value"]["node_id"] == "lent"]
        # Le capteur bavard ne garde que ses 2 derniers messages et n'evince
        # pas l'historique du capteur lent
        assert bavard == [3, 4]
        assert lent == [100]

    def test_taille_historique_par_defaut(self):
        hub = TopicHub(default_history=3)
        for i in range(10):
            hub.publish("t", make_record(offset=i, timestamp_ms=i))
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [7, 8, 9]

    def test_client_lent_perd_les_plus_anciens(self):
        hub = TopicHub()
        hub.CLIENT_QUEUE_MARGIN = 2
        queue = hub.subscribe("t")  # maxsize = 0 rejeu + 2

        for i in range(4):
            hub.publish("t", make_record(offset=i))

        assert [r["offset"] for r in drain(queue)] == [2, 3]


class TestObservateurDuBus:
    async def test_on_record_diffuse_et_historise(self):
        hub = TopicHub()
        queue = hub.subscribe("t")
        record = make_record(offset=1)

        await hub.on_record("t", record, replay=False)

        assert drain(queue) == [avec_capteur(record)]
        assert drain(hub.subscribe("t")) == [avec_capteur(record)]

    async def test_records_rejoues_aussi_diffuses_et_historises(self):
        """Le hub ne filtre pas replay=True : remplir l'historique au
        demarrage est le role du prechauffage."""
        hub = TopicHub()
        queue = hub.subscribe("t")

        await hub.on_record("t", make_record(offset=1), replay=True)

        assert [r["offset"] for r in drain(queue)] == [1]
        assert [r["offset"] for r in drain(hub.subscribe("t"))] == [1]

    async def test_on_record_idempotent(self):
        """Un record relu par le prechauffage puis consomme en temps reel
        n'est diffuse et historise qu'une fois."""
        hub = TopicHub()
        queue = hub.subscribe("t")

        await hub.on_record("t", make_record(offset=5), replay=True)
        await hub.on_record("t", make_record(offset=5), replay=False)

        assert len(drain(queue)) == 1
        assert len(drain(hub.subscribe("t"))) == 1

    async def test_inscrit_sur_le_bus(self):
        hub = TopicHub()
        queue_a, queue_b = hub.subscribe("a"), hub.subscribe("b")
        bus = RecordBus()
        bus.subscribe(hub)

        await bus.publish("a", make_record(topic="a", offset=1))
        await bus.publish("b", make_record(topic="b", offset=2), replay=True)

        assert [r["offset"] for r in drain(queue_a)] == [1]
        assert [r["offset"] for r in drain(queue_b)] == [2]
