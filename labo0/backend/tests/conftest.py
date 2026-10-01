"""Fixtures partagees par les tests du backend."""

from types import SimpleNamespace

import pytest

from app.config import Settings, TopicConfig


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


@pytest.fixture
def plaintext_settings(tmp_path):
    """Settings sans SSL/SASL et sans lecture du YAML."""
    def _make(topic_configs=None, **overrides):
        return Settings(
            security_protocol=overrides.pop("security_protocol", "PLAINTEXT"),
            output_dir=overrides.pop("output_dir", str(tmp_path)),
            topic_configs=topic_configs if topic_configs is not None else [
                TopicConfig("topic.a", history_per_sensor=10, warmup_messages=5),
                TopicConfig("topic.b", history_per_sensor=10, warmup_messages=0),
            ],
            **overrides,
        )
    return _make
