import asyncio

from app.data_management.data_distribution.queues import (
    offer_dropping_oldest,
    offer_or_reset,
)
from tests.conftest import drain


class TestOfferDroppingOldest:
    def test_simple_offer(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        offer_dropping_oldest(queue, 1)
        assert drain(queue) == [1]

    def test_full_queue_drops_oldest(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        for item in range(4):
            offer_dropping_oldest(queue, item)
        assert drain(queue) == [2, 3]

    def test_unbounded_queue(self):
        queue: asyncio.Queue = asyncio.Queue()
        for item in range(5):
            offer_dropping_oldest(queue, item)
        assert queue.qsize() == 5


class TestOfferOrReset:
    def test_offer_without_overflow(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        offer_or_reset(queue, 1, lambda: "etat")
        offer_or_reset(queue, 2, lambda: "etat")
        assert drain(queue) == [1, 2]

    def test_full_queue_replaced_by_full_state(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        appels = []

        def full_state():
            appels.append(1)
            return "etat"

        for item in (1, 2, 3):
            offer_or_reset(queue, item, full_state)

        # Debordement : file remplacee par l'etat complet, calcule a la demande
        assert drain(queue) == ["etat"]
        assert appels == [1]
        offer_or_reset(queue, 4, full_state)
        assert drain(queue) == [4]
