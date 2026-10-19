"""Files clientes WebSocket : un client lent ne bloque jamais la diffusion."""

import asyncio
from collections.abc import Callable


def offer_dropping_oldest(queue: asyncio.Queue, item: object) -> None:
    """Depose sans attendre ; file pleine : jette le plus ancien message.
    Aucun await : atomique dans la boucle asyncio."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        queue.get_nowait()
        queue.put_nowait(item)


def offer_or_reset(queue: asyncio.Queue, item: object,
                   reset: Callable[[], object]) -> None:
    """Depose sans attendre ; file pleine : remplace tout son contenu par
    `reset()`, l'etat complet (un evenement perdu fausserait le client).
    Aucun await : atomique dans la boucle asyncio."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(reset())
