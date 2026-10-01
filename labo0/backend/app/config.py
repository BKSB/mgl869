"""Configuration du service.

Connexion Kafka : variables d'environnement (backend/.env).
Topics et historiques : fichier YAML (TOPICS_CONFIG, backend/config/topics.yaml),
avec repli sur KAFKA_TOPICS / les defauts si le fichier est absent.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_TOPICS = [
    "gridd.obs.environmental.temperature",
    "gridd.obs.environmental.humidity",
    "gridd.obs.environmental.co2",
    "gridd.obs.acoustic.sound_level",
    "gridd.obs.occupancy.count",
]


def _env(name: str, default: str) -> str:
    """Variable d'environnement, avec repli sur la valeur par defaut si elle
    est absente OU vide (un .env peut contenir des lignes `CLE=` vides)."""
    return os.getenv(name) or default


@dataclass
class TopicConfig:
    """Reglages d'un topic consomme."""
    name: str
    # Messages conserves et rejoues par capteur (node_id) sur le WebSocket
    history_per_sensor: int
    # Messages relus par partition au demarrage pour remplir l'historique
    warmup_messages: int


def _load_topic_configs(default_history: int, default_warmup: int) -> list[TopicConfig]:
    """Charge les topics depuis le YAML ; repli sur KAFKA_TOPICS / defauts."""
    path = Path(_env("TOPICS_CONFIG", "config/topics.yaml"))
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults = data.get("defaults") or {}
        default_history = int(defaults.get("history_per_sensor", default_history))
        default_warmup = int(defaults.get("warmup_messages", default_warmup))
        topics = data.get("topics") or {}
        if not topics:
            raise ValueError(f"{path} : aucun topic defini sous la cle 'topics'")
        return [
            TopicConfig(
                name=name,
                history_per_sensor=int((cfg or {}).get("history_per_sensor",
                                                       default_history)),
                warmup_messages=int((cfg or {}).get("warmup_messages",
                                                    default_warmup)),
            )
            for name, cfg in topics.items()
        ]

    logger.warning("Fichier de topics introuvable (%s) : repli sur "
                   "KAFKA_TOPICS / topics par defaut", path)
    names = [t.strip()
             for t in _env("KAFKA_TOPICS", ",".join(DEFAULT_TOPICS)).split(",")
             if t.strip()]
    return [TopicConfig(name, default_history, default_warmup) for name in names]


@dataclass
class Settings:
    bootstrap_servers: str = _env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9093")
    group_id_prefix: str = _env("KAFKA_GROUP_ID_PREFIX", "gridd-consumer")
    auto_offset_reset: str = _env("KAFKA_AUTO_OFFSET_RESET", "earliest")

    # Securite : SASL (utilisateur/mot de passe) sur SSL, verification du
    # broker via certificat CA
    security_protocol: str = _env("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    ssl_ca_location: str = _env(
        "KAFKA_SSL_CA_LOCATION", "/etc/gridd/kafka/gridd-kafka-ca.crt"
    )
    sasl_mechanism: str = _env("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256")
    sasl_username: str = os.getenv("KAFKA_USERNAME", "")
    sasl_password: str = os.getenv("KAFKA_PASSWORD", "")

    # Repertoire ou chaque topic ecrit ses messages (un fichier JSONL par topic)
    output_dir: str = _env("OUTPUT_DIR", "/var/lib/gridd/data")

    # Topics et leurs reglages, charges du YAML (defauts surchargables par
    # HISTORY_PER_SENSOR / WARMUP_MESSAGES quand le YAML ne les fixe pas)
    topic_configs: list[TopicConfig] = field(default_factory=lambda: _load_topic_configs(
        default_history=int(_env("HISTORY_PER_SENSOR", "100")),
        default_warmup=int(_env("WARMUP_MESSAGES", "1000")),
    ))

    @property
    def topics(self) -> list[str]:
        return [t.name for t in self.topic_configs]

    def consumer_config(self, topic: str | None = None) -> dict:
        """Parametres AIOKafkaConsumer. Avec un topic : group_id dedie a ce
        topic (chaque topic est consomme independamment, avec ses propres
        offsets) ; sans topic : pas de groupe (assignation manuelle, ex.
        prechauffage d'historique)."""
        from aiokafka.helpers import create_ssl_context

        protocol = self.security_protocol.upper()
        config: dict = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": f"{self.group_id_prefix}.{topic}" if topic else None,
            "auto_offset_reset": self.auto_offset_reset,
            "enable_auto_commit": False,
            "security_protocol": protocol,
        }
        if protocol in ("SSL", "SASL_SSL"):
            config["ssl_context"] = create_ssl_context(cafile=self.ssl_ca_location)
        if protocol.startswith("SASL"):
            config["sasl_mechanism"] = self.sasl_mechanism
            config["sasl_plain_username"] = self.sasl_username
            config["sasl_plain_password"] = self.sasl_password
        return config
