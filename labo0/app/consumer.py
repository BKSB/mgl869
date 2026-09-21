"""Consommateur Kafka dedie a un seul topic, execute dans son propre thread."""

import json
import logging
import threading
from pathlib import Path

from confluent_kafka import Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)


class TopicConsumer(threading.Thread):
    """Consomme un topic Kafka et ecrit chaque message dans un fichier JSONL
    propre au topic. Un thread par topic : les donnees de chaque topic sont
    recuperees et traitees separement."""

    POLL_TIMEOUT_S = 1.0

    def __init__(self, topic: str, consumer_config: dict, output_dir: str,
                 stop_event: threading.Event):
        super().__init__(name=f"consumer-{topic}", daemon=True)
        self.topic = topic
        self.consumer_config = consumer_config
        self.stop_event = stop_event
        self.output_path = Path(output_dir) / f"{topic}.jsonl"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        consumer = Consumer(self.consumer_config)
        try:
            consumer.subscribe([self.topic])
            logger.info("[%s] abonne, en attente de messages", self.topic)
            with self.output_path.open("a", encoding="utf-8") as out:
                while not self.stop_event.is_set():
                    msg = consumer.poll(self.POLL_TIMEOUT_S)
                    if msg is None:
                        continue
                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        logger.error("[%s] erreur Kafka : %s", self.topic, msg.error())
                        continue
                    self._handle(msg, out)
                    consumer.commit(msg, asynchronous=False)
        except KafkaException:
            logger.exception("[%s] erreur fatale du consommateur", self.topic)
        finally:
            consumer.close()
            logger.info("[%s] consommateur ferme", self.topic)

    def _handle(self, msg, out) -> None:
        raw = msg.value().decode("utf-8", errors="replace") if msg.value() else None
        try:
            value = json.loads(raw) if raw is not None else None
        except json.JSONDecodeError:
            value = raw  # message non JSON : conserve tel quel

        record = {
            "topic": msg.topic(),
            "partition": msg.partition(),
            "offset": msg.offset(),
            "timestamp_ms": msg.timestamp()[1],
            "key": msg.key().decode("utf-8", errors="replace") if msg.key() else None,
            "value": value,
        }
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        out.flush()
        logger.info("[%s] partition=%d offset=%d recu", msg.topic(),
                    msg.partition(), msg.offset())
