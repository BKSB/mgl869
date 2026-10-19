"""Tests des politiques de files clientes : flux de mesures (les plus
anciennes sont perdues) et flux snapshot + evenements (etat complet)."""

import asyncio

from app.data_management.data_distribution.queues import (
    offer_dropping_oldest,
    offer_or_reset,
)


def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


class TestOfferDroppingOldest:
    def test_file_pleine_perd_le_plus_ancien(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        for item in (1, 2, 3):
            offer_dropping_oldest(queue, item)
        assert drain(queue) == [2, 3]


class TestOfferOrReset:
    def test_depose_sans_debordement(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        offer_or_reset(queue, 1, lambda: "etat")
        offer_or_reset(queue, 2, lambda: "etat")
        assert drain(queue) == [1, 2]

    def test_file_pleine_remplacee_par_l_etat_complet(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        appels = []

        def etat():
            appels.append(1)
            return "etat"

        for item in (1, 2, 3):
            offer_or_reset(queue, item, etat)

        # Le message qui deborde est remplace, avec tous ceux en attente,
        # par l'etat complet (calcule seulement au debordement)
        assert drain(queue) == ["etat"]
        assert appels == [1]
        offer_or_reset(queue, 4, etat)
        assert drain(queue) == [4]
