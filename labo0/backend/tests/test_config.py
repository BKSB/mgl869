import logging

import pytest
import yaml

from app.config import (
    DEFAULT_HISTORY_PER_SENSOR,
    DEFAULT_WARMUP_MESSAGES,
    AlertsConfig,
    Settings,
    TopicConfig,
    _env,
    _load_topic_configs,
    load_alerts_config,
)
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    WARNING,
    AlertRule,
)


class TestEnv:
    def test_defined_value(self, monkeypatch):
        monkeypatch.setenv("GRIDD_TEST_VAR", "x")
        assert _env("GRIDD_TEST_VAR", "defaut") == "x"

    def test_missing_or_empty(self, monkeypatch):
        monkeypatch.delenv("GRIDD_TEST_VAR", raising=False)
        assert _env("GRIDD_TEST_VAR", "defaut") == "defaut"
        monkeypatch.setenv("GRIDD_TEST_VAR", "")
        assert _env("GRIDD_TEST_VAR", "defaut") == "defaut"


class TestLoadTopicConfigs:
    def write_yaml(self, monkeypatch, tmp_path, content: str):
        path = tmp_path / "topics.yaml"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setenv("TOPICS_CONFIG", str(path))

    def test_yaml_with_defaults_and_overrides(self, monkeypatch, tmp_path):
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

    def test_yaml_without_defaults(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path, "topics:\n  a: {}\n")
        assert _load_topic_configs() == [
            TopicConfig("a", DEFAULT_HISTORY_PER_SENSOR,
                        DEFAULT_WARMUP_MESSAGES)]

    @pytest.mark.parametrize("content", ["", "topics: {}\n", "defaults: {}\n"])
    def test_yaml_without_topics(self, monkeypatch, tmp_path, content):
        self.write_yaml(monkeypatch, tmp_path, content)
        with pytest.raises(ValueError, match="aucun topic"):
            _load_topic_configs()

    def test_missing_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TOPICS_CONFIG", str(tmp_path / "absent.yaml"))
        with pytest.raises(FileNotFoundError, match="absent.yaml"):
            _load_topic_configs()

    def test_duplicate_topic_rejected(self, monkeypatch, tmp_path):
        """PyYAML garderait le second bloc en silence (historique perdu)."""
        self.write_yaml(monkeypatch, tmp_path,
                        "topics:\n  a: {}\n  b: {}\n  a:\n    history_per_sensor: 7\n")
        with pytest.raises(yaml.YAMLError, match="cle dupliquee : 'a'"):
            _load_topic_configs()

    @pytest.mark.parametrize("content", [
        "- a\n- b\n",                                  # liste a la racine
        "topics:\n  - a\n",                            # liste de topics
        "topics:\n  a: [1]\n",                         # reglages en liste
        "topics:\n  a:\n    history_per_sensor: beaucoup\n",
        "defaults: 3\ntopics:\n  a: {}\n",
    ])
    def test_invalid_structure_message_names_file(self, monkeypatch,
                                                  tmp_path, content):
        self.write_yaml(monkeypatch, tmp_path, content)
        with pytest.raises(ValueError, match="topics.yaml : contenu invalide"):
            _load_topic_configs()

    def test_environment_variables_ignored(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path, "topics:\n  a: {}\n")
        monkeypatch.setenv("KAFKA_TOPICS", "x,y")
        monkeypatch.setenv("HISTORY_PER_SENSOR", "7")
        monkeypatch.setenv("WARMUP_MESSAGES", "9")
        assert _load_topic_configs() == [
            TopicConfig("a", DEFAULT_HISTORY_PER_SENSOR,
                        DEFAULT_WARMUP_MESSAGES)]

    def test_repo_file_valid(self, monkeypatch):
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

    def test_environment_read_at_instantiation(self, monkeypatch):
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker-test:9092")
        monkeypatch.setenv("KAFKA_USERNAME", "u")
        monkeypatch.setenv("KAFKA_PASSWORD", "")
        settings = Settings(topic_configs=[], alerts=AlertsConfig())
        assert settings.bootstrap_servers == "broker-test:9092"
        assert settings.sasl_username == "u"
        assert settings.sasl_password == ""

    @pytest.mark.parametrize("protocol,ssl,sasl", [
        ("PLAINTEXT", False, False),
        ("ssl", True, False),
        ("SASL_PLAINTEXT", False, True),
        ("SASL_SSL", True, True),
    ])
    def test_ssl_and_sasl_by_protocol(self, protocol, ssl, sasl):
        settings = self.make(security_protocol=protocol)
        assert (settings.uses_ssl, settings.uses_sasl) == (ssl, sasl)

    def test_consumer_config_plaintext(self):
        config = self.make(security_protocol="plaintext").consumer_config("a")
        assert config == {
            "bootstrap_servers": "broker:9093",
            "group_id": "grp.a",
            "auto_offset_reset": "earliest",
            "enable_auto_commit": False,
            "security_protocol": "PLAINTEXT",
        }

    def test_consumer_config_without_topic_has_no_group(self):
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


class TestValidate:
    def test_valid_configuration(self, plaintext_settings):
        assert plaintext_settings().validate() == []

    def test_ca_certificate_not_found(self, plaintext_settings, tmp_path):
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(tmp_path / "absent.crt"))
        errors = settings.validate()
        assert len(errors) == 1
        assert "Certificat CA introuvable" in errors[0]

    def test_ca_certificate_present(self, plaintext_settings, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_text("cert")
        settings = plaintext_settings(security_protocol="SSL",
                                      ssl_ca_location=str(ca))
        assert settings.validate() == []

    @pytest.mark.parametrize("username,password", [("", ""), ("u", ""), ("", "p")])
    def test_sasl_credentials_required(self, plaintext_settings, username, password):
        settings = plaintext_settings(security_protocol="SASL_PLAINTEXT",
                                      sasl_username=username,
                                      sasl_password=password)
        assert any("KAFKA_USERNAME" in e for e in settings.validate())

    def test_no_topic(self, plaintext_settings):
        errors = plaintext_settings(topic_configs=[]).validate()
        assert any("Aucun topic" in e for e in errors)

    def test_valid_alerts(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, rules={
            "topic.a": [AlertRule(WARNING, ABOVE, 1)]})
        assert plaintext_settings(alerts=alerts).validate() == []

    def test_invalid_alerts(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, source="alerts.yaml",
                              errors=["alerts.yaml : severite inconnue"])
        assert plaintext_settings(alerts=alerts).validate() == \
            ["alerts.yaml : severite inconnue"]

    def test_alert_on_unconsumed_topic(self, plaintext_settings):
        alerts = AlertsConfig(enabled=True, source="alerts.yaml", rules={
            "topic.inconnu": [AlertRule(WARNING, ABOVE, 1)]})
        (error,) = plaintext_settings(alerts=alerts).validate()
        assert "topic non consomme" in error
        assert "topic.inconnu" in error


class TestLoadAlertsConfig:
    def write_yaml(self, monkeypatch, tmp_path, content: str) -> str:
        path = tmp_path / "alerts.yaml"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setenv("ALERTS_CONFIG", str(path))
        return str(path)

    def test_missing_file_disables_alerts(self, monkeypatch, tmp_path,
                                               caplog):
        monkeypatch.setenv("ALERTS_CONFIG", str(tmp_path / "absent.yaml"))
        with caplog.at_level(logging.WARNING):
            config = load_alerts_config()

        assert not config.enabled
        assert config.rules == {}
        assert config.validate(["a"]) == []
        assert "absent.yaml" in caplog.text
        assert "alertes desactivees" in caplog.text

    def test_default_path(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ALERTS_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "alerts.yaml").write_text(
            "rules:\n  a:\n    - { severity: warning, above: 1 }\n",
            encoding="utf-8")
        assert load_alerts_config().rules == {"a": [AlertRule(WARNING, ABOVE, 1)]}

    def test_valid_file_with_defaults(self, monkeypatch, tmp_path):
        source = self.write_yaml(monkeypatch, tmp_path, """
defaults:
  hysteresis: 2
rules:
  a:
    - { severity: warning, above: 1000 }
    - { severity: critical, above: 1500, hysteresis: 50 }
  b:
    - { severity: warning, below: 18.5, hysteresis: 0 }
""")
        config = load_alerts_config()

        assert config.enabled
        assert config.errors == []
        assert config.source == source
        assert config.rules == {
            "a": [AlertRule(WARNING, ABOVE, 1000.0, 2.0),
                  AlertRule(CRITICAL, ABOVE, 1500.0, 50.0)],
            "b": [AlertRule(WARNING, BELOW, 18.5, 0.0)],
        }
        assert config.validate(["a", "b", "c"]) == []

    def test_default_hysteresis_is_zero(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path,
                        "rules:\n  a:\n    - { severity: warning, above: 1 }\n")
        (regle,) = load_alerts_config().rules["a"]
        assert regle.hysteresis == 0.0

    @pytest.mark.parametrize("content", [
        "",
        "rules: {}\n",
        "defaults: {}\n",
        "rules:\n  a:\n",
        "rules:\n  a: []\n",
        # Cle presente mais vide (None) : equivaut a une cle absente
        "rules:\n",
        "defaults:\nrules:\n",
    ])
    def test_file_without_rules(self, monkeypatch, tmp_path, content):
        self.write_yaml(monkeypatch, tmp_path, content)
        config = load_alerts_config()
        assert config.enabled
        assert config.rules == {}
        assert config.errors == []

    @pytest.mark.parametrize("regle,attendu", [
        ("{ severity: majeure, above: 1 }", "severite inconnue : 'majeure'"),
        ("{ severity: Warning, above: 1 }", "severite inconnue : 'Warning'"),
        ("{ above: 1 }", "severite manquante"),
        ("{ severity: warning, over: 1 }",
         "direction inconnue ou cle invalide : over"),
        ("{ severity: warning, above: 1, seuil: 2 }",
         "direction inconnue ou cle invalide : seuil"),
        ("{ severity: warning }", "direction manquante"),
        ("{ severity: warning, hysteresis: 1 }", "direction manquante"),
        ("{ severity: warning, above: 1, below: 2 }", "une seule direction"),
        ("{ severity: warning, above: beaucoup }",
         "seuil non numerique pour above : 'beaucoup'"),
        ("{ severity: warning, below: '18' }",
         "seuil non numerique pour below : '18'"),
        ("{ severity: warning, above: true }", "seuil non numerique"),
        ("{ severity: warning, above: .nan }", "seuil non numerique"),
        ("{ severity: warning, above: }", "seuil non numerique"),
        # Entier trop grand pour un float : erreur claire, pas d'OverflowError
        ("{ severity: warning, above: 1" + "0" * 400 + " }",
         "seuil non numerique pour above"),
        ("{ severity: warning, above: 1, hysteresis: -1 }",
         "hysteresis negative : -1"),
        ("{ severity: warning, above: 1, hysteresis: un peu }",
         "hysteresis non numerique : 'un peu'"),
        ("warning", "regle attendue sous la forme"),
    ])
    def test_invalid_rule(self, monkeypatch, tmp_path, regle, attendu):
        source = self.write_yaml(monkeypatch, tmp_path,
                                 f"rules:\n  a:\n    - {{ severity: warning, "
                                 f"above: 1 }}\n    - {regle}\n")
        config = load_alerts_config()

        (erreur,) = config.validate(["a"])
        assert erreur.startswith(f"{source} : a, regle 2 : ")
        assert attendu in erreur
        # La regle valide est conservee, l'invalide ecartee
        assert config.rules == {"a": [AlertRule(WARNING, ABOVE, 1.0)]}

    def test_multiple_errors_in_one_rule(self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path,
                        "rules:\n  a:\n    - { severity: x, above: y }\n")
        config = load_alerts_config()
        assert len(config.validate(["a"])) == 2
        assert config.rules == {}

    @pytest.mark.parametrize("content,attendu", [
        ("- a\n- b\n", "dictionnaire attendu a la racine"),
        ("regles: {}\n", "cle(s) inconnue(s) a la racine : regles"),
        ("defaults: [1]\n", "'defaults' doit etre un dictionnaire"),
        # Valeurs "fausses" non vides : erreurs de saisie, pas un dict vide
        ("defaults: 0\n", "'defaults' doit etre un dictionnaire"),
        ("defaults: false\n", "'defaults' doit etre un dictionnaire"),
        ("defaults: []\n", "'defaults' doit etre un dictionnaire"),
        ("defaults: { hysteresis: 1, seuil: 2 }\n",
         "cle(s) inconnue(s) dans defaults : seuil"),
        ("defaults: { hysteresis: -0.5 }\n",
         "defaults : hysteresis negative"),
        ("defaults: { hysteresis: beaucoup }\n",
         "defaults : hysteresis non numerique"),
        ("rules: [a, b]\n", "'rules' doit associer chaque topic"),
        ("rules: false\n", "'rules' doit associer chaque topic"),
        ("rules: 0\n", "'rules' doit associer chaque topic"),
        ("rules: ''\n", "'rules' doit associer chaque topic"),
        ("rules: []\n", "'rules' doit associer chaque topic"),
        ("rules:\n  a: { severity: warning, above: 1 }\n",
         "a : liste de regles attendue"),
        ("rules: [\n", "fichier d'alertes illisible"),
        # Plus de 4300 chiffres (limite de Python) : ValueError au decodage
        ("rules:\n  a:\n    - { severity: warning, above: 1"
         + "0" * 5000 + " }\n", "fichier d'alertes illisible"),
    ])
    def test_invalid_structure(self, monkeypatch, tmp_path, content, attendu):
        self.write_yaml(monkeypatch, tmp_path, content)
        config = load_alerts_config()

        erreurs = config.validate([])
        assert len(erreurs) == 1
        assert attendu in erreurs[0]

    @pytest.mark.parametrize("content,cle,ligne", [
        # Deux blocs pour le meme topic : le premier disparaitrait
        ("rules:\n  a:\n    - { severity: warning, above: 1000 }\n"
         "  a:\n    - { severity: critical, above: 1500 }\n", "'a'", 4),
        # Deux seuils dans une regle : le premier serait remplace en silence
        ("rules:\n  a:\n    - { severity: warning, above: 1000, above: 1500 }\n",
         "'above'", 3),
        ("defaults: { hysteresis: 1 }\ndefaults: { hysteresis: 2 }\n",
         "'defaults'", 2),
    ])
    def test_duplicate_key(self, monkeypatch, tmp_path, content, cle, ligne):
        source = self.write_yaml(monkeypatch, tmp_path, content)
        config = load_alerts_config()

        assert config.validate([]) == [
            f"{source} : fichier d'alertes invalide : cle dupliquee : {cle} "
            f"(ligne {ligne})"]
        assert config.rules == {}

    def test_redefined_merge_key_accepted(self, monkeypatch, tmp_path):
        """Cle fusionnee (<<) redefinie : surcharge YAML, pas un doublon."""
        self.write_yaml(monkeypatch, tmp_path, """
rules:
  a:
    - &base { severity: warning, above: 1 }
    - { <<: *base, above: 2 }
""")
        config = load_alerts_config()
        assert config.errors == []
        assert config.rules == {"a": [AlertRule(WARNING, ABOVE, 1.0),
                                      AlertRule(WARNING, ABOVE, 2.0)]}

    def test_invalid_default_hysteresis_replaced_by_zero(
            self, monkeypatch, tmp_path):
        self.write_yaml(monkeypatch, tmp_path, """
defaults: { hysteresis: -1 }
rules:
  a:
    - { severity: warning, above: 1 }
""")
        config = load_alerts_config()
        assert len(config.errors) == 1
        assert config.rules["a"][0].hysteresis == 0.0

    def test_rule_on_unconsumed_topic(self, monkeypatch, tmp_path):
        source = self.write_yaml(monkeypatch, tmp_path, """
rules:
  a:
    - { severity: warning, above: 1 }
  gridd.inconnu:
    - { severity: warning, above: 1 }
""")
        config = load_alerts_config()

        assert config.errors == []
        assert config.validate(["a"]) == [
            f"{source} : regles d'alerte sur un topic non consomme "
            "(absent de topics.yaml) : gridd.inconnu"]

    def test_repo_file_valid(self, monkeypatch):
        monkeypatch.setenv("TOPICS_CONFIG", "config/topics.yaml")
        monkeypatch.setenv("ALERTS_CONFIG", "config/alerts.yaml")
        topics = [t.name for t in _load_topic_configs()]
        config = load_alerts_config()

        assert config.enabled
        assert config.validate(topics) == []
        assert config.rules["gridd.obs.environmental.co2"] == [
            AlertRule(WARNING, ABOVE, 1000, 50),
            AlertRule(CRITICAL, ABOVE, 1500, 50),
        ]
        temperature = config.rules["gridd.obs.environmental.temperature"]
        assert {(r.severity, r.direction, r.threshold) for r in temperature} == {
            (WARNING, BELOW, 18), (WARNING, ABOVE, 26),
            (CRITICAL, BELOW, 16), (CRITICAL, ABOVE, 28)}
        assert all(r.hysteresis == 0.5 for r in temperature)
        assert len(config.rules["gridd.obs.environmental.humidity"]) == 4
        assert len(config.rules["gridd.obs.acoustic.sound_level"]) == 2
        # Occupation : aucune regle active (capacite des salles inconnue)
        assert "gridd.obs.occupancy.count" not in config.rules

    def test_settings_loads_alerts(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ALERTS_CONFIG", str(tmp_path / "absent.yaml"))
        settings = Settings(topic_configs=[TopicConfig("a", 1, 0)])
        assert settings.alerts == AlertsConfig(enabled=False,
                                               source=str(tmp_path / "absent.yaml"))
