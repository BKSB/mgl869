"""Fixtures partagees par les tests du backend."""

from types import SimpleNamespace

import pytest

from app.config import AlertsConfig, Settings, TopicConfig


def make_msg(topic="t", partition=0, offset=0, timestamp=1000,
             key=b"k", value=b'{"node_id": "n1", "v": 1}'):
    """Faux message Kafka (memes attributs qu'un ConsumerRecord aiokafka)."""
    return SimpleNamespace(topic=topic, partition=partition, offset=offset,
                           timestamp=timestamp, key=key, value=value)


def make_record(node_id="n1", partition=0, offset=0, timestamp_ms=1000,
                topic="t", key=None):
    """Record tel que produit par record_from_msg."""
    return {
        "topic": topic,
        "partition": partition,
        "offset": offset,
        "timestamp_ms": timestamp_ms,
        "key": key,
        "value": {"node_id": node_id} if node_id else None,
    }


def make_mesure(valeur=20.0, timestamp_ms=1000, offset=0, node_id="n1",
                partition=0, topic="t", unit="ppm", zone="Zone A",
                space="Salle 101"):
    """Record de mesure capteur complet (payload gridd avec metadonnees)."""
    metadata = {}
    if zone is not None:
        metadata["zone"] = {"id": "z1", "label": zone}
    if space is not None:
        metadata["space"] = {"id": "s1", "label": space}
    return {
        "topic": topic,
        "partition": partition,
        "offset": offset,
        "timestamp_ms": timestamp_ms,
        "key": None,
        "value": {"node_id": node_id, "type": "mesure", "value": valeur,
                  "unit": unit, "metadata": metadata},
    }


class Collecteur:
    """Callback d'acquisition asynchrone (meme signature que la publication
    sur le bus fournie par le service) : accumule les records recus."""

    def __init__(self):
        self.records: list[dict] = []

    async def __call__(self, record: dict) -> None:
        self.records.append(record)


class ObservateurEspion:
    """Observateur du bus de records qui journalise chaque notification sous
    la forme (nom, topic, offset, replay). Plusieurs espions peuvent partager
    le meme journal pour verifier l'ordre de notification."""

    def __init__(self, nom: str = "espion", journal: list | None = None):
        self.nom = nom
        self.journal = journal if journal is not None else []

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        self.journal.append((self.nom, topic, record.get("offset"), replay))


class ObservateurEnPanne:
    """Observateur dont chaque notification echoue."""

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        raise RuntimeError("panne simulee")


@pytest.fixture
def plaintext_settings(tmp_path):
    """Settings sans SSL/SASL et sans lecture des YAML (alertes desactivees
    sauf si `alerts` est fourni)."""
    def _make(topic_configs=None, **overrides):
        return Settings(
            security_protocol=overrides.pop("security_protocol", "PLAINTEXT"),
            output_dir=overrides.pop("output_dir", str(tmp_path)),
            topic_configs=topic_configs if topic_configs is not None else [
                TopicConfig("topic.a", history_per_sensor=10, warmup_messages=5),
                TopicConfig("topic.b", history_per_sensor=10, warmup_messages=0),
            ],
            alerts=overrides.pop("alerts", AlertsConfig()),
            **overrides,
        )
    return _make
