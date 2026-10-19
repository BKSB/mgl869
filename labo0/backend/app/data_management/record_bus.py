"""Bus de records : patron Observateur entre l'acquisition et ses usages.

L'acquisition (consommateurs Kafka, prechauffage d'historique) ne connait
que le bus, le Sujet : elle lui publie chaque record, et le bus le transmet
a tous les observateurs inscrits. Le hub WebSocket est le premier
observateur, le service d'alertes le deuxieme ; les futurs services
(registre des capteurs, historique en base, qualite des donnees)
s'inscrivent a leur tour dans le composition root (app/main.py), sans
modifier l'acquisition.
"""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class RecordObserver(Protocol):
    """Observateur des records Kafka (typage structurel : toute classe qui
    definit `on_record` avec cette signature convient, sans heritage)."""

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        """Recoit un record publie sur le bus.

        Contrat :
        - appele dans la boucle asyncio, sequentiellement avec les autres
          observateurs et AVANT le commit de l'offset : doit etre rapide, ou
          deleguer tout travail lent ou bloquant (asyncio.to_thread, file
          traitee par une tache dediee) ;
        - doit etre idempotent : la livraison Kafka est "au moins une fois"
          (un message notifie mais pas encore commite est relu apres un
          redemarrage) et le prechauffage peut relire des messages deja vus.
          Un record est identifie par (topic, partition, offset) ;
        - replay=True : record relu au demarrage (prechauffage) ou anterieur
          au demarrage du service (rattrapage d'un retard) : il sert a
          reconstruire un etat, ce n'est pas un evenement nouveau. Un
          observateur peut s'en servir pour son etat (historique, registre,
          alertes actives) mais n'en tire aucun evenement (ni notification,
          ni annonce) ;
        - une exception est journalisee par le bus et n'affecte ni les
          autres observateurs ni le commit : le record n'est pas renvoye a
          cet observateur.
        """


class RecordBus:
    """Sujet du patron Observateur : diffuse chaque record a ses
    observateurs, dans l'ordre d'inscription, en isolant leurs pannes."""

    def __init__(self) -> None:
        self._observers: list[RecordObserver] = []

    @property
    def observers(self) -> tuple[RecordObserver, ...]:
        """Observateurs inscrits, dans l'ordre d'inscription."""
        return tuple(self._observers)

    def subscribe(self, observer: RecordObserver) -> None:
        """Inscrit un observateur (sans effet s'il l'est deja)."""
        # Comparaison par identite : deux observateurs distincts mais
        # "egaux" (ex. dataclasses) restent deux inscriptions
        if any(o is observer for o in self._observers):
            return
        self._observers.append(observer)
        logger.info("Observateur inscrit sur le bus de records : %s",
                    type(observer).__name__)

    def unsubscribe(self, observer: RecordObserver) -> None:
        """Desinscrit un observateur (sans erreur s'il est absent)."""
        self._observers = [o for o in self._observers if o is not observer]

    async def publish(self, topic: str, record: dict, *,
                      replay: bool = False) -> None:
        """Notifie chaque observateur, sequentiellement et dans l'ordre
        d'inscription. La panne d'un observateur est journalisee sans
        interrompre la diffusion ; une annulation se propage toujours."""
        # Copie : un observateur peut (se) desinscrire ou en inscrire un
        # autre pendant la notification sans perturber ce parcours
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
