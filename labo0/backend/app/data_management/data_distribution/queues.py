"""Files clientes WebSocket, sans await (atomiques dans la boucle asyncio) :
un client lent ne bloque jamais la diffusion."""

import asyncio
from collections.abc import Callable


def offer_dropping_oldest(queue: asyncio.Queue, item: object) -> None:
    """File pleine : jette le plus ancien message."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        queue.get_nowait()
        queue.put_nowait(item)


def offer_or_reset(queue: asyncio.Queue, item: object,
                   reset: Callable[[], object]) -> None:
    """File pleine : remplace tout son contenu par `reset()`, l'etat complet
    (un evenement perdu fausserait le client)."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(reset())
