"""Configuration du service, chargee depuis les variables d'environnement."""

import os
from dataclasses import dataclass, field

DEFAULT_TOPICS = [
    "gridd.obs.environmental.temperature",
    "gridd.obs.acoustic.sound_level",
    "gridd.derived.environmental.thermal_comfort",
    "gridd.derived.occupancy.estimated_count",
    "gridd.alert.environmental.high_co2",
    "gridd.alert.acoustic.high_sound_level",
]


def _env(name: str, default: str) -> str:
    """Variable d'environnement, avec repli sur la valeur par defaut si elle
    est absente OU vide (un .env peut contenir des lignes `CLE=` vides)."""
    return os.getenv(name) or default


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
    sasl_mechanism: str = _env("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512")
    sasl_username: str = os.getenv("KAFKA_USERNAME", "")
    sasl_password: str = os.getenv("KAFKA_PASSWORD", "")

    # Liste de topics separes par des virgules ; sinon les topics gridd par defaut
    topics: list[str] = field(default_factory=lambda: [
        t.strip()
        for t in _env("KAFKA_TOPICS", ",".join(DEFAULT_TOPICS)).split(",")
        if t.strip()
    ])

    # Repertoire ou chaque topic ecrit ses messages (un fichier JSONL par topic)
    output_dir: str = _env("OUTPUT_DIR", "/var/lib/gridd/data")

    def consumer_config(self, topic: str) -> dict:
        """Configuration confluent-kafka pour un consommateur dedie a un topic."""
        config = {
            "bootstrap.servers": self.bootstrap_servers,
            # Un group.id distinct par topic : chaque topic est consomme
            # independamment, avec ses propres offsets.
            "group.id": f"{self.group_id_prefix}.{topic}",
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": False,
            "security.protocol": self.security_protocol,
        }
        protocol = self.security_protocol.upper()
        if protocol in ("SSL", "SASL_SSL"):
            config["ssl.ca.location"] = self.ssl_ca_location
        if protocol.startswith("SASL"):
            config["sasl.mechanism"] = self.sasl_mechanism
            config["sasl.username"] = self.sasl_username
            config["sasl.password"] = self.sasl_password
        return config
