"""Politiques des files clientes (WebSocket) : une diffusion ne bloque jamais
sur un client trop lent, elle ne fait que reduire ce qu'il recevra."""

import asyncio
from collections.abc import Callable


def offer_dropping_oldest(queue: asyncio.Queue, item: object) -> None:
    """Depose `item` sans jamais attendre ; si la file est pleine, jette
    d'abord le message le plus ancien (flux de mesures : un client trop lent
    perd ses mesures les plus anciennes).

    A appeler depuis la boucle asyncio (aucun `await` : le retrait et le
    depot sont atomiques). Une file pleine n'est jamais vide (maxsize > 0),
    donc le retrait ne peut pas echouer."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        queue.get_nowait()
        queue.put_nowait(item)


def offer_or_reset(queue: asyncio.Queue, item: object,
                   reset: Callable[[], object]) -> None:
    """Depose `item` sans jamais attendre ; si la file est pleine, la vide et
    y depose `reset()` a la place.

    Pour un flux "etat complet puis changements" (snapshot puis evenements),
    ou chaque message perdu fausserait l'etat du client : l'etat complet
    courant remplace tous les messages en attente. A appeler depuis la
    boucle asyncio (aucun `await`)."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(reset())
