"""Kafka : environnement (.env). Topics et regles d'alerte : fichiers YAML
designes par TOPICS_CONFIG et ALERTS_CONFIG (optionnel)."""

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.data_management.data_processing.alert_rules import (
    DIRECTIONS,
    SEVERITIES,
    AlertRule,
    is_number,
)

logger = logging.getLogger(__name__)

# Defauts quand le YAML ne fixe la valeur ni sur le topic ni dans `defaults`
DEFAULT_HISTORY_PER_SENSOR = 100
DEFAULT_WARMUP_MESSAGES = 1000


def _env(name: str, default: str) -> str:
    """Vide vaut absent : un .env peut contenir des lignes `CLE=`."""
    return os.getenv(name) or default


def _env_field(name: str, default: str) -> str:
    """Lu a chaque instanciation de Settings, pas a l'import du module."""
    return field(default_factory=lambda: _env(name, default))


class _UniqueKeyLoader(yaml.SafeLoader):
    """Refuse les cles dupliquees, que PyYAML ecraserait en silence."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _value in node.value:
            # Cle de fusion (<<) : les cles fusionnees peuvent etre redefinies
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError:
                continue  # cle non hashable : signalee par construct_mapping
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    None, None, f"cle dupliquee : {key!r}", key_node.start_mark)
        return super().construct_mapping(node, deep=deep)


def _load_yaml(path: Path) -> object:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)


@dataclass
class TopicConfig:
    name: str
    # Par capteur : messages gardes et rejoues a la connexion WebSocket
    history_per_sensor: int
    # Par partition : messages relus au demarrage (prechauffage)
    warmup_messages: int


def _load_topic_configs() -> list[TopicConfig]:
    """Absent : FileNotFoundError ; invalide : ValueError ou yaml.YAMLError."""
    path = Path(_env("TOPICS_CONFIG", "config/topics.yaml"))
    if not path.is_file():
        raise FileNotFoundError(f"Fichier de topics introuvable : {path}")
    data = _load_yaml(path) or {}
    try:
        defaults = data.get("defaults") or {}
        default_history = int(defaults.get("history_per_sensor",
                                           DEFAULT_HISTORY_PER_SENSOR))
        default_warmup = int(defaults.get("warmup_messages",
                                           DEFAULT_WARMUP_MESSAGES))
        topics = data.get("topics") or {}
        configs = [
            TopicConfig(
                name=name,
                history_per_sensor=int((cfg or {}).get("history_per_sensor",
                                                       default_history)),
                warmup_messages=int((cfg or {}).get("warmup_messages",
                                                    default_warmup)),
            )
            for name, cfg in topics.items()
        ]
    # Structure inattendue : message nommant le fichier, pas une traceback
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{path} : contenu invalide ({exc})") from exc
    if not configs:
        raise ValueError(f"{path} : aucun topic defini sous la cle 'topics'")
    return configs


# Cles admises dans alerts.yaml
_ALERTS_ROOT_KEYS = ("defaults", "rules")
_ALERTS_DEFAULT_KEYS = ("hysteresis",)
_ALERT_RULE_KEYS = ("severity", *DIRECTIONS, "hysteresis")


@dataclass
class AlertsConfig:
    """Erreurs de contenu collectees (pas levees), remontees par validate."""
    # Faux si le fichier est absent
    enabled: bool = False
    # topic -> regles, dans l'ordre du fichier (topics sans regle omis)
    rules: dict[str, list[AlertRule]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Chemin du fichier, pour les messages
    source: str = ""

    def validate(self, topics: Iterable[str]) -> list[str]:
        """Erreurs du chargement, plus les regles sur un topic non consomme."""
        consumed = set(topics)
        return [*self.errors, *(
            f"{self.source} : regles d'alerte sur un topic non consomme "
            f"(absent de topics.yaml) : {topic}"
            for topic in self.rules if topic not in consumed)]


def _unknown_keys(data: dict, allowed: Iterable[str]) -> str:
    return ", ".join(sorted(str(k) for k in data if k not in allowed))


def _parse_hysteresis(raw: object, where: str,
                      errors: list[str]) -> float | None:
    """Nombre fini >= 0, sinon None (erreur ajoutee a `errors`)."""
    if not is_number(raw):
        errors.append(f"{where} : hysteresis non numerique : {raw!r}")
        return None
    if raw < 0:
        errors.append(f"{where} : hysteresis negative : {raw!r} (attendu >= 0)")
        return None
    return float(raw)


def _parse_alert_rule(entry: object, default_hysteresis: float,
                      where: str, errors: list[str]) -> AlertRule | None:
    """`{ severity, above|below, hysteresis? }`, ou None si invalide."""
    if not isinstance(entry, dict):
        errors.append(f"{where} : regle attendue sous la forme "
                      f"{{ severity: ..., above|below: ... }}, recu {entry!r}")
        return None
    # Erreurs de cette regle seule : errors cumule celles du fichier
    problems: list[str] = []

    severity = entry.get("severity")
    if "severity" not in entry:
        problems.append(f"{where} : severite manquante (warning ou critical)")
    elif severity not in SEVERITIES:
        problems.append(f"{where} : severite inconnue : {severity!r} "
                        "(attendu : warning ou critical)")

    unknown = _unknown_keys(entry, _ALERT_RULE_KEYS)
    if unknown:
        problems.append(f"{where} : direction inconnue ou cle invalide : "
                        f"{unknown} (attendu : severity, above ou below, "
                        "hysteresis)")
    directions = [d for d in DIRECTIONS if d in entry]
    threshold = None
    if len(directions) > 1:
        problems.append(f"{where} : une seule direction par regle "
                        "(above ou below)")
    elif not directions:
        if not unknown:
            problems.append(f"{where} : direction manquante (above ou below)")
    elif not is_number(entry[directions[0]]):
        problems.append(f"{where} : seuil non numerique pour "
                        f"{directions[0]} : {entry[directions[0]]!r}")
    else:
        threshold = float(entry[directions[0]])

    hysteresis = default_hysteresis
    if "hysteresis" in entry:
        hysteresis = _parse_hysteresis(entry["hysteresis"], where, problems)

    errors.extend(problems)
    if problems:
        return None
    return AlertRule(severity=severity, direction=directions[0],
                     threshold=threshold, hysteresis=hysteresis)


def _parse_defaults(data: dict, source: str, errors: list[str]) -> float:
    """Hysteresis de `defaults` ; 0 si absente ou invalide."""
    # Seul None vaut absent : 0, false, "" ou [] sont des erreurs de saisie
    defaults = data.get("defaults")
    if defaults is None:
        return 0.0
    if not isinstance(defaults, dict):
        errors.append(f"{source} : 'defaults' doit etre un dictionnaire")
        return 0.0
    unknown = _unknown_keys(defaults, _ALERTS_DEFAULT_KEYS)
    if unknown:
        errors.append(f"{source} : cle(s) inconnue(s) dans defaults : "
                      f"{unknown} (attendu : hysteresis)")
    if "hysteresis" not in defaults:
        return 0.0
    parsed = _parse_hysteresis(defaults["hysteresis"], f"{source} : defaults",
                               errors)
    return 0.0 if parsed is None else parsed


def _parse_rule_sections(data: dict, source: str, default_hysteresis: float,
                         errors: list[str]) -> dict[str, list[AlertRule]]:
    """Regles valides par topic ; topics sans regle valide omis."""
    sections = data.get("rules")
    if sections is None:
        return {}
    if not isinstance(sections, dict):
        errors.append(f"{source} : 'rules' doit associer chaque topic a une "
                      "liste de regles")
        return {}
    rules: dict[str, list[AlertRule]] = {}
    for topic, entries in sections.items():
        if entries is None:
            continue  # topic cite sans regle
        if not isinstance(entries, list):
            errors.append(f"{source} : {topic} : liste de regles attendue, "
                          f"recu {entries!r}")
            continue
        parsed_rules = [
            _parse_alert_rule(entry, default_hysteresis,
                              f"{source} : {topic}, regle {i}", errors)
            for i, entry in enumerate(entries, start=1)
        ]
        valid = [rule for rule in parsed_rules if rule is not None]
        if valid:
            rules[str(topic)] = valid
    return rules


def parse_alerts(data: object, source: str) -> AlertsConfig:
    """Depuis le YAML deja decode ; erreurs collectees, pas levees."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return AlertsConfig(enabled=True, source=source, errors=[
            f"{source} : dictionnaire attendu a la racine (cles defaults, "
            "rules)"])
    errors: list[str] = []
    unknown = _unknown_keys(data, _ALERTS_ROOT_KEYS)
    if unknown:
        errors.append(f"{source} : cle(s) inconnue(s) a la racine : {unknown} "
                      "(attendu : defaults, rules)")
    default_hysteresis = _parse_defaults(data, source, errors)
    rules = _parse_rule_sections(data, source, default_hysteresis, errors)
    return AlertsConfig(enabled=True, rules=rules, errors=errors,
                        source=source)


def load_alerts_config() -> AlertsConfig:
    """Absent : alertes desactivees, le service demarre quand meme. Illisible
    ou invalide : erreurs collectees, le demarrage est refuse."""
    path = Path(_env("ALERTS_CONFIG", "config/alerts.yaml"))
    if not path.is_file():
        logger.warning("Fichier d'alertes introuvable (%s) : alertes "
                       "desactivees", path)
        return AlertsConfig(enabled=False, source=str(path))
    try:
        data = _load_yaml(path)
    # Contenu refuse a la construction (cle dupliquee, etiquette inconnue)
    except yaml.constructor.ConstructorError as exc:
        line = f" (ligne {exc.problem_mark.line + 1})" if exc.problem_mark else ""
        return AlertsConfig(enabled=True, source=str(path), errors=[
            f"{path} : fichier d'alertes invalide : {exc.problem}{line}"])
    # ValueError : UnicodeDecodeError, entier > 4300 chiffres (limite Python)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return AlertsConfig(enabled=True, source=str(path), errors=[
            f"{path} : fichier d'alertes illisible ({exc})"])
    return parse_alerts(data, str(path))


@dataclass
class Settings:
    bootstrap_servers: str = _env_field("KAFKA_BOOTSTRAP_SERVERS",
                                        "localhost:9093")
    group_id_prefix: str = _env_field("KAFKA_GROUP_ID_PREFIX", "gridd-consumer")
    auto_offset_reset: str = _env_field("KAFKA_AUTO_OFFSET_RESET", "earliest")

    # Securite : SASL sur SSL, broker verifie par le certificat CA
    security_protocol: str = _env_field("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    ssl_ca_location: str = _env_field(
        "KAFKA_SSL_CA_LOCATION", "/etc/gridd/kafka/gridd-kafka-ca.crt"
    )
    sasl_mechanism: str = _env_field("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256")
    sasl_username: str = _env_field("KAFKA_USERNAME", "")
    sasl_password: str = _env_field("KAFKA_PASSWORD", "")

    # Un fichier JSONL par topic
    output_dir: str = _env_field("OUTPUT_DIR", "/var/lib/gridd/data")

    topic_configs: list[TopicConfig] = field(default_factory=_load_topic_configs)

    alerts: AlertsConfig = field(default_factory=load_alerts_config)

    @property
    def topics(self) -> list[str]:
        return [t.name for t in self.topic_configs]

    @property
    def uses_ssl(self) -> bool:
        return self.security_protocol.upper() in ("SSL", "SASL_SSL")

    @property
    def uses_sasl(self) -> bool:
        return self.security_protocol.upper().startswith("SASL")

    def validate(self) -> list[str]:
        """Erreurs empechant le demarrage ; vide si tout est valide."""
        errors = []
        if self.uses_ssl and not Path(self.ssl_ca_location).is_file():
            errors.append(f"Certificat CA introuvable : {self.ssl_ca_location}")
        if self.uses_sasl and not (self.sasl_username and self.sasl_password):
            errors.append("KAFKA_USERNAME / KAFKA_PASSWORD requis avec le "
                          f"protocole {self.security_protocol}")
        if not self.topics:
            errors.append("Aucun topic configure (config/topics.yaml)")
        errors.extend(self.alerts.validate(self.topics))
        return errors

    def consumer_config(self, topic: str | None = None) -> dict:
        """Avec `topic` : groupe dedie, donc offsets propres au topic ; sans :
        aucun groupe (prechauffage)."""
        from aiokafka.helpers import create_ssl_context

        config: dict = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": f"{self.group_id_prefix}.{topic}" if topic else None,
            "auto_offset_reset": self.auto_offset_reset,
            "enable_auto_commit": False,
            "security_protocol": self.security_protocol.upper(),
        }
        if self.uses_ssl:
            config["ssl_context"] = create_ssl_context(cafile=self.ssl_ca_location)
        if self.uses_sasl:
            config["sasl_mechanism"] = self.sasl_mechanism
            config["sasl_plain_username"] = self.sasl_username
            config["sasl_plain_password"] = self.sasl_password
        return config
