"""Configuration du service.

Connexion Kafka : variables d'environnement (backend/.env).
Topics et historiques : fichier YAML (TOPICS_CONFIG, backend/config/topics.yaml),
seule source de la liste des topics.
Regles d'alerte : fichier YAML optionnel (ALERTS_CONFIG,
backend/config/alerts.yaml) ; absent, les alertes sont desactivees.
"""

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
    """Variable d'environnement, avec repli sur la valeur par defaut si elle
    est absente OU vide (un .env peut contenir des lignes `CLE=` vides)."""
    return os.getenv(name) or default


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader qui refuse les cles dupliquees d'un dictionnaire. PyYAML
    garde sinon la derniere valeur en silence : un bloc de regles ou un
    seuil disparaitrait sans qu'aucune validation ne le voie."""

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
    """Contenu d'un fichier YAML, cles dupliquees refusees
    (yaml.constructor.ConstructorError)."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)


@dataclass
class TopicConfig:
    """Reglages d'un topic consomme."""
    name: str
    # Messages conserves et rejoues par capteur (node_id) sur le WebSocket
    history_per_sensor: int
    # Messages relus par partition au demarrage pour remplir l'historique
    warmup_messages: int


def _load_topic_configs() -> list[TopicConfig]:
    """Charge la liste des topics et leurs reglages depuis le YAML."""
    path = Path(_env("TOPICS_CONFIG", "config/topics.yaml"))
    if not path.is_file():
        raise FileNotFoundError(f"Fichier de topics introuvable : {path}")
    data = _load_yaml(path) or {}
    defaults = data.get("defaults") or {}
    default_history = int(defaults.get("history_per_sensor",
                                       DEFAULT_HISTORY_PER_SENSOR))
    default_warmup = int(defaults.get("warmup_messages",
                                       DEFAULT_WARMUP_MESSAGES))
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


# Cles admises dans alerts.yaml
_ALERTS_ROOT_KEYS = ("defaults", "rules")
_ALERTS_DEFAULT_KEYS = ("hysteresis",)
_ALERT_RULE_KEYS = ("severity", *DIRECTIONS, "hysteresis")


@dataclass
class AlertsConfig:
    """Regles d'alerte par topic, chargees du YAML (ALERTS_CONFIG).

    Le chargement ne leve pas d'exception sur un contenu invalide : les
    erreurs sont collectees dans `errors` et remontees par `validate`, que le
    service appelle avant de demarrer (il refuse alors de demarrer)."""
    # Faux si le fichier est absent : aucune alerte n'est evaluee
    enabled: bool = False
    # topic -> regles, dans l'ordre du fichier (topics sans regle omis)
    rules: dict[str, list[AlertRule]] = field(default_factory=dict)
    # Erreurs de contenu detectees au chargement
    errors: list[str] = field(default_factory=list)
    # Chemin du fichier, pour les messages
    source: str = ""

    def validate(self, topics: Iterable[str]) -> list[str]:
        """Erreurs de la configuration : celles du chargement, plus les
        regles portant sur un topic qui n'est pas consomme."""
        consumed = set(topics)
        return [*self.errors, *(
            f"{self.source} : regles d'alerte sur un topic non consomme "
            f"(absent de topics.yaml) : {topic}"
            for topic in self.rules if topic not in consumed)]


def _unknown_keys(data: dict, allowed: Iterable[str]) -> str:
    """Cles de `data` hors de `allowed`, triees et separees par des virgules
    ("" si aucune)."""
    return ", ".join(sorted(str(k) for k in data if k not in allowed))


def _parse_hysteresis(raw: object, where: str,
                      errors: list[str]) -> float | None:
    """Hysteresis validee (nombre fini >= 0), ou None apres avoir ajoute
    l'erreur a `errors`."""
    if not is_number(raw):
        errors.append(f"{where} : hysteresis non numerique : {raw!r}")
        return None
    if raw < 0:
        errors.append(f"{where} : hysteresis negative : {raw!r} (attendu >= 0)")
        return None
    return float(raw)


def _parse_alert_rule(entry: object, default_hysteresis: float,
                      where: str, errors: list[str]) -> AlertRule | None:
    """Une regle `{ severity, above|below, hysteresis? }` ; None si elle est
    invalide (erreurs ajoutees a `errors`)."""
    if not isinstance(entry, dict):
        errors.append(f"{where} : regle attendue sous la forme "
                      f"{{ severity: ..., above|below: ... }}, recu {entry!r}")
        return None
    count = len(errors)

    severity = entry.get("severity")
    if "severity" not in entry:
        errors.append(f"{where} : severite manquante (warning ou critical)")
    elif severity not in SEVERITIES:
        errors.append(f"{where} : severite inconnue : {severity!r} "
                      "(attendu : warning ou critical)")

    unknown = _unknown_keys(entry, _ALERT_RULE_KEYS)
    if unknown:
        errors.append(f"{where} : direction inconnue ou cle invalide : "
                      f"{unknown} (attendu : severity, above ou below, "
                      "hysteresis)")
    directions = [d for d in DIRECTIONS if d in entry]
    threshold = None
    if len(directions) > 1:
        errors.append(f"{where} : une seule direction par regle "
                      "(above ou below)")
    elif not directions:
        if not unknown:
            errors.append(f"{where} : direction manquante (above ou below)")
    elif not is_number(entry[directions[0]]):
        errors.append(f"{where} : seuil non numerique pour "
                      f"{directions[0]} : {entry[directions[0]]!r}")
    else:
        threshold = float(entry[directions[0]])

    hysteresis = default_hysteresis
    if "hysteresis" in entry:
        hysteresis = _parse_hysteresis(entry["hysteresis"], where, errors)

    if len(errors) > count:
        return None
    return AlertRule(severity=severity, direction=directions[0],
                     threshold=threshold, hysteresis=hysteresis)


def parse_alerts(data: object, source: str) -> AlertsConfig:
    """Construit la configuration des alertes depuis le contenu du YAML
    (deja decode) ; les erreurs de contenu sont collectees, pas levees."""
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

    default_hysteresis = 0.0
    # Seul None (cle absente ou valeur vide) vaut "rien" : 0, false, "" ou []
    # sont des erreurs de saisie, pas un dictionnaire vide
    defaults = data.get("defaults")
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        errors.append(f"{source} : 'defaults' doit etre un dictionnaire")
    else:
        unknown = _unknown_keys(defaults, _ALERTS_DEFAULT_KEYS)
        if unknown:
            errors.append(f"{source} : cle(s) inconnue(s) dans defaults : "
                          f"{unknown} (attendu : hysteresis)")
        if "hysteresis" in defaults:
            parsed = _parse_hysteresis(defaults["hysteresis"],
                                       f"{source} : defaults", errors)
            if parsed is not None:
                default_hysteresis = parsed

    rules: dict[str, list[AlertRule]] = {}
    sections = data.get("rules")
    if sections is None:
        sections = {}
    if not isinstance(sections, dict):
        errors.append(f"{source} : 'rules' doit associer chaque topic a une "
                      "liste de regles")
        sections = {}
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
    return AlertsConfig(enabled=True, rules=rules, errors=errors,
                        source=source)


def load_alerts_config() -> AlertsConfig:
    """Charge les regles d'alerte du YAML (ALERTS_CONFIG). Fichier absent :
    alertes desactivees (avertissement), le service demarre. Fichier
    illisible ou invalide : erreurs collectees (voir AlertsConfig.validate)."""
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
    # ValueError couvre UnicodeDecodeError et un entier de plus de 4300
    # chiffres (limite de conversion de Python, levee pendant le decodage)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return AlertsConfig(enabled=True, source=str(path), errors=[
            f"{path} : fichier d'alertes illisible ({exc})"])
    return parse_alerts(data, str(path))


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

    # Topics et leurs reglages, charges du YAML
    topic_configs: list[TopicConfig] = field(default_factory=_load_topic_configs)

    # Regles d'alerte, chargees du YAML (desactivees si le fichier manque)
    alerts: AlertsConfig = field(default_factory=load_alerts_config)

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
