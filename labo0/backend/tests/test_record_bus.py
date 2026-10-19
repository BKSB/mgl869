"""Tests du bus de records (patron Observateur) : ordre de notification,
inscription / desinscription, isolation des pannes, propagation de
l'annulation et transmission du drapeau replay."""

import asyncio
import logging

import pytest

from app.data_management.record_bus import RecordBus
from tests.conftest import ObservateurEnPanne, ObservateurEspion, make_record


class TestInscription:
    def test_bus_vide(self):
        assert RecordBus().observers == ()

    def test_observers_dans_l_ordre_d_inscription(self):
        bus = RecordBus()
        a, b, c = ObservateurEspion("a"), ObservateurEspion("b"), ObservateurEspion("c")
        for observer in (b, a, c):
            bus.subscribe(observer)

        assert bus.observers == (b, a, c)
        # Tuple : une vue en lecture seule, pas la liste interne
        assert isinstance(bus.observers, tuple)

    def test_subscribe_idempotent(self):
        bus = RecordBus()
        espion = ObservateurEspion()
        bus.subscribe(espion)
        bus.subscribe(espion)

        assert bus.observers == (espion,)

    async def test_subscribe_idempotent_une_seule_notification(self):
        bus = RecordBus()
        espion = ObservateurEspion()
        bus.subscribe(espion)
        bus.subscribe(espion)

        await bus.publish("t", make_record(offset=1))

        assert espion.journal == [("espion", "t", 1, False)]

    def test_observateurs_egaux_mais_distincts_inscrits_tous_deux(self):
        class Egal(ObservateurEspion):
            def __eq__(self, other):
                return True

            __hash__ = None

        bus = RecordBus()
        bus.subscribe(Egal("1"))
        bus.subscribe(Egal("2"))

        assert len(bus.observers) == 2

    def test_unsubscribe(self):
        bus = RecordBus()
        a, b = ObservateurEspion("a"), ObservateurEspion("b")
        bus.subscribe(a)
        bus.subscribe(b)

        bus.unsubscribe(a)

        assert bus.observers == (b,)

    def test_unsubscribe_absent_sans_erreur(self):
        bus = RecordBus()
        present = ObservateurEspion()
        bus.subscribe(present)

        bus.unsubscribe(ObservateurEspion("absent"))

        assert bus.observers == (present,)

    def test_inscription_journalisee(self, caplog):
        with caplog.at_level(logging.INFO):
            RecordBus().subscribe(ObservateurEspion())
        assert "ObservateurEspion" in caplog.text


class TestPublish:
    async def test_publish_sans_observateur(self):
        await RecordBus().publish("t", make_record())

    async def test_notifie_dans_l_ordre_d_inscription(self):
        journal = []
        bus = RecordBus()
        for nom in ("premier", "deuxieme", "troisieme"):
            bus.subscribe(ObservateurEspion(nom, journal))

        await bus.publish("t", make_record(offset=4))

        assert [entree[0] for entree in journal] == ["premier", "deuxieme", "troisieme"]
        assert all(entree[1:] == ("t", 4, False) for entree in journal)

    async def test_notification_sequentielle(self):
        """Un observateur qui suspend son traitement (await) est attendu
        jusqu'au bout avant que le suivant ne soit notifie."""
        journal = []

        class Lent:
            async def on_record(self, topic, record, *, replay):
                journal.append("lent:debut")
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                journal.append("lent:fin")

        bus = RecordBus()
        bus.subscribe(Lent())
        bus.subscribe(ObservateurEspion("rapide", journal))

        await bus.publish("t", make_record(offset=0))

        assert journal == ["lent:debut", "lent:fin", ("rapide", "t", 0, False)]

    async def test_replay_faux_par_defaut(self):
        bus = RecordBus()
        espion = ObservateurEspion()
        bus.subscribe(espion)

        await bus.publish("t", make_record(offset=1))
        await bus.publish("t", make_record(offset=2), replay=True)

        assert espion.journal == [("espion", "t", 1, False),
                                  ("espion", "t", 2, True)]

    async def test_record_transmis_tel_quel(self):
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

    async def test_desinscription_pendant_la_notification(self):
        """Un observateur qui se desinscrit pendant sa notification ne fait
        sauter aucun des suivants (le bus itere sur une copie)."""
        journal = []
        bus = RecordBus()

        class UneSeuleFois(ObservateurEspion):
            async def on_record(self, topic, record, *, replay):
                await super().on_record(topic, record, replay=replay)
                bus.unsubscribe(self)

        bus.subscribe(UneSeuleFois("ephemere", journal))
        bus.subscribe(ObservateurEspion("b", journal))
        bus.subscribe(ObservateurEspion("c", journal))

        await bus.publish("t", make_record(offset=0))
        await bus.publish("t", make_record(offset=1))

        assert journal == [
            ("ephemere", "t", 0, False), ("b", "t", 0, False), ("c", "t", 0, False),
            ("b", "t", 1, False), ("c", "t", 1, False),
        ]
        assert [o.nom for o in bus.observers] == ["b", "c"]

    async def test_inscription_pendant_la_notification(self):
        """Un observateur inscrit pendant une notification ne recoit que les
        records publies apres son inscription."""
        journal = []
        bus = RecordBus()
        tardif = ObservateurEspion("tardif", journal)

        class Parrain(ObservateurEspion):
            async def on_record(self, topic, record, *, replay):
                await super().on_record(topic, record, replay=replay)
                bus.subscribe(tardif)

        bus.subscribe(Parrain("parrain", journal))

        await bus.publish("t", make_record(offset=0))
        await bus.publish("t", make_record(offset=1))

        assert journal == [
            ("parrain", "t", 0, False),
            ("parrain", "t", 1, False), ("tardif", "t", 1, False),
        ]


class TestIsolationDesPannes:
    async def test_panne_n_empeche_pas_les_suivants(self, caplog):
        journal = []
        bus = RecordBus()
        bus.subscribe(ObservateurEspion("avant", journal))
        bus.subscribe(ObservateurEnPanne())
        bus.subscribe(ObservateurEspion("apres", journal))

        with caplog.at_level(logging.ERROR):
            # publish ne leve pas malgre la panne
            await bus.publish("topic.x", make_record(partition=3, offset=42))

        assert [entree[0] for entree in journal] == ["avant", "apres"]

        erreurs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(erreurs) == 1
        message = erreurs[0].getMessage()
        assert "ObservateurEnPanne" in message
        assert "topic.x" in message
        assert "partition=3" in message
        assert "offset=42" in message
        # Trace de la pile conservee (logger.exception)
        assert erreurs[0].exc_info is not None
        assert "panne simulee" in caplog.text

    async def test_panne_a_chaque_record_n_arrete_pas_le_bus(self):
        journal = []
        bus = RecordBus()
        bus.subscribe(ObservateurEnPanne())
        bus.subscribe(ObservateurEspion("sain", journal))

        for offset in range(3):
            await bus.publish("t", make_record(offset=offset))

        assert [entree[2] for entree in journal] == [0, 1, 2]
        # L'observateur en panne reste inscrit
        assert len(bus.observers) == 2

    async def test_record_sans_partition_ni_offset_journalise(self, caplog):
        bus = RecordBus()
        bus.subscribe(ObservateurEnPanne())

        with caplog.at_level(logging.ERROR):
            await bus.publish("t", {"value": "brut"})

        assert "partition=None offset=None" in caplog.text

    async def test_annulation_propagee(self):
        journal = []

        class Annule:
            async def on_record(self, topic, record, *, replay):
                raise asyncio.CancelledError

        bus = RecordBus()
        bus.subscribe(Annule())
        bus.subscribe(ObservateurEspion("suivant", journal))

        with pytest.raises(asyncio.CancelledError):
            await bus.publish("t", make_record())

        # L'annulation interrompt la diffusion : rien n'est avale
        assert journal == []

    async def test_annulation_de_la_tache_pendant_une_notification(self):
        """Annuler la tache qui publie (arret du service) interrompt
        l'observateur en cours et se propage a l'appelant."""
        en_cours = asyncio.Event()

        class Bloquant:
            async def on_record(self, topic, record, *, replay):
                en_cours.set()
                await asyncio.Event().wait()

        bus = RecordBus()
        bus.subscribe(Bloquant())
        tache = asyncio.create_task(bus.publish("t", make_record()))
        await en_cours.wait()

        tache.cancel()

        with pytest.raises(asyncio.CancelledError):
            await tache
        assert tache.cancelled()
