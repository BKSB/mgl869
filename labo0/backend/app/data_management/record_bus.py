"""Patron Observateur : l'acquisition ne connait que le bus ; les
observateurs s'inscrivent dans le composition root (main.create_bus)."""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class RecordObserver(Protocol):
    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Contrat :
        - boucle asyncio, en serie avec les autres observateurs et AVANT le
          commit : rapide, ou deleguer le travail lent (asyncio.to_thread) ;
        - idempotent sur (topic, partition, offset) : livraison au moins une
          fois, et le suiveur et le consommateur livrent les memes records ;
        - replay=True (prechauffage, rattrapage) : mise a jour d'etat
          seulement, aucun evenement (ni notification ni annonce) ;
        - exception journalisee par le bus, sans effet sur les autres
          observateurs ni sur le commit : le record n'est pas renvoye."""


class RecordBus:
    def __init__(self) -> None:
        self._observers: list[RecordObserver] = []

    @property
    def observers(self) -> tuple[RecordObserver, ...]:
        return tuple(self._observers)

    def subscribe(self, observer: RecordObserver) -> None:
        # Identite, pas egalite : des observateurs egaux restent distincts
        if any(o is observer for o in self._observers):
            return
        self._observers.append(observer)
        logger.info("Observateur inscrit sur le bus de records : %s",
                    type(observer).__name__)

    def unsubscribe(self, observer: RecordObserver) -> None:
        self._observers = [o for o in self._observers if o is not observer]

    async def publish(self, topic: str, record: dict, *,
                      replay: bool = False) -> None:
        """En serie et dans l'ordre d'inscription ; pannes isolees."""
        # Copie : un observateur peut (des)inscrire pendant la notification
        for observer in tuple(self._observers):
            try:
                await observer.on_record(topic, record, replay=replay)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[%s] observateur %s en echec (partition=%s offset=%s) : "
                    "record ignore par cet observateur",
                    topic, type(observer).__name__,
                    record.get("partition"), record.get("offset"))
