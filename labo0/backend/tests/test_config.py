"""Tests de la configuration : chargement des topics depuis le YAML et
parametres du consommateur Kafka."""

import pytest

from app.config import (
    DEFAULT_HISTORY_PER_SENSOR,
    DEFAULT_WARMUP_MESSAGES,
    Settings,
    TopicConfig,
    _env,
    _load_topic_configs,
)


class TestEnv:
    def test_valeur_definie(self, monkeypatch):
        monkeypatch.setenv("GRIDD_TEST_VAR", "x")
        assert _env("GRIDD_TEST_VAR", "defaut") == "x"

    def test_absente_ou_vide(self, monkeypatch):
        monkeypatch.delenv("GRIDD_TEST_VAR", raising=False)
        assert _env("GRIDD_TEST_VAR", "defaut") == "defaut"
        monkeypatch.setenv("GRIDD_TEST_VAR", "")
        assert _env("GRIDD_TEST_VAR", "defaut") == "defaut"


class TestLoadTopicConfigs:
    def write_yaml(self, monkeypatch, tmp_path, content: str):
        path = tmp_path / "topics.yaml"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setenv("TOPICS_CONFIG", str(path))

    def test_yaml_avec_defauts_et_surcharges(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path, """
defaults:
  history_per_sensor: 50
  warmup_messages: 200
topics:
  a: {}
  b:
    history_per_sensor: 7
  c:
""")
        assert _load_topic_configs() == [
            TopicConfig("a", 50, 200),
            TopicConfig("b", 7, 200),
            TopicConfig("c", 50, 200),
        ]

    def test_yaml_sans_defauts(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path, "topics:\n  a: {}\n")
        assert _load_topic_configs() == [
            TopicConfig("a", DEFAULT_HISTORY_PER_SENSOR,
                        DEFAULT_WARMUP_MESSAGES)]

    @pytest.mark.parametrize("content", ["", "topics: {}\n", "defaults: {}\n"])
    def test_yaml_sans_topic(self, monkeypatch, tmp_path, content):
        self.write_yaml(monkeypatch, tmp_path, content)
        with pytest.raises(ValueError, match="aucun topic"):
            _load_topic_configs()

    def test_fichier_absent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TOPICS_CONFIG", str(tmp_path / "absent.yaml"))
        with pytest.raises(FileNotFoundError, match="absent.yaml"):
            _load_topic_configs()

    def test_variables_d_environnement_ignorees(self, monkeypatch, tmp_path):
        """KAFKA_TOPICS / HISTORY_PER_SENSOR / WARMUP_MESSAGES ne sont plus lues : le YAML
        est la seule source."""
        self.write_yaml(monkeypatch, tmp_path, "topics:\n  a: {}\n")
        monkeypatch.setenv("KAFKA_TOPICS", "x,y")
        monkeypatch.setenv("HISTORY_PER_SENSOR", "7")
        monkeypatch.setenv("WARMUP_MESSAGES", "9")
        assert _load_topic_configs() == [
            TopicConfig("a", DEFAULT_HISTORY_PER_SENSOR,
                        DEFAULT_WARMUP_MESSAGES)]

    def test_fichier_du_depot_valide(self, monkeypatch):
        monkeypatch.setenv("TOPICS_CONFIG", "config/topics.yaml")
        configs = {t.name: t for t in _load_topic_configs()}
        assert set(configs) == {
            "gridd.obs.environmental.temperature",
            "gridd.obs.environmental.humidity",
            "gridd.obs.environmental.co2",
            "gridd.obs.acoustic.sound_level",
            "gridd.obs.occupancy.count",
        }
        assert configs["gridd.obs.acoustic.sound_level"].history_per_sensor == 1800


class TestSettings:
    def make(self, **kwargs) -> Settings:
        kwargs.setdefault("topic_configs", [TopicConfig("a", 1, 0),
                                            TopicConfig("b", 1, 0)])
        return Settings(bootstrap_servers="broker:9093", group_id_prefix="grp",
                        auto_offset_reset="earliest", **kwargs)

    def test_topics(self):
        assert self.make().topics == ["a", "b"]

    def test_consumer_config_plaintext(self):
        config = self.make(security_protocol="plaintext").consumer_config("a")
        assert config == {
            "bootstrap_servers": "broker:9093",
            "group_id": "grp.a",
            "auto_offset_reset": "earliest",
            "enable_auto_commit": False,
            "security_protocol": "PLAINTEXT",
        }

    def test_consumer_config_sans_topic_sans_groupe(self):
        config = self.make(security_protocol="PLAINTEXT").consumer_config()
        assert config["group_id"] is None

    def test_consumer_config_sasl_plaintext(self):
        config = self.make(security_protocol="SASL_PLAINTEXT",
                           sasl_mechanism="SCRAM-SHA-512",
                           sasl_username="u", sasl_password="p").consumer_config("a")
        assert config["sasl_mechanism"] == "SCRAM-SHA-512"
        assert config["sasl_plain_username"] == "u"
        assert config["sasl_plain_password"] == "p"
        assert "ssl_context" not in config

    def test_consumer_config_sasl_ssl(self, monkeypatch):
        calls = []
        monkeypatch.setattr("aiokafka.helpers.create_ssl_context",
                            lambda cafile: calls.append(cafile) or "ctx")
        config = self.make(security_protocol="SASL_SSL",
                           ssl_ca_location="/ca.crt",
                           sasl_username="u", sasl_password="p").consumer_config("a")
        assert config["ssl_context"] == "ctx"
        assert calls == ["/ca.crt"]
        assert config["sasl_plain_username"] == "u"
