"""Point d'entree : demarre un consommateur par topic et gere l'arret propre."""

import logging
import signal
import sys
import threading
from pathlib import Path

from app.config import Settings
from app.consumer import TopicConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    settings = Settings()

    protocol = settings.security_protocol.upper()

    ca_path = Path(settings.ssl_ca_location)
    if protocol in ("SSL", "SASL_SSL") and not ca_path.is_file():
        logger.error("Certificat CA introuvable : %s", ca_path)
        return 1

    if protocol.startswith("SASL") and not (settings.sasl_username and settings.sasl_password):
        logger.error("KAFKA_USERNAME / KAFKA_PASSWORD requis avec le protocole %s",
                     settings.security_protocol)
        return 1

    if not settings.topics:
        logger.error("Aucun topic configure (KAFKA_TOPICS)")
        return 1

    stop_event = threading.Event()

    def shutdown(signum, _frame):
        logger.info("Signal %s recu, arret en cours...", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info("Demarrage : %d topic(s) sur %s (protocole %s)",
                len(settings.topics), settings.bootstrap_servers,
                settings.security_protocol)

    threads = [
        TopicConsumer(
            topic=topic,
            consumer_config=settings.consumer_config(topic),
            output_dir=settings.output_dir,
            stop_event=stop_event,
        )
        for topic in settings.topics
    ]
    for t in threads:
        t.start()

    # Attend l'arret demande par signal, tout en surveillant les threads
    while not stop_event.is_set():
        stop_event.wait(timeout=5)
        dead = [t for t in threads if not t.is_alive()]
        if dead:
            logger.error("Consommateur(s) arrete(s) inopinement : %s",
                         [t.topic for t in dead])
            stop_event.set()

    for t in threads:
        t.join(timeout=10)

    logger.info("Service arrete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

