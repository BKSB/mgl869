"""Evaluation des regles d'alerte : logique pure, sans asyncio ni I/O.

Chaque capteur a un niveau d'alerte (aucun, warning, critical) recalcule a
chaque mesure a partir des regles de son topic :

- une regle `above` s'active quand la valeur depasse STRICTEMENT le seuil et
  reste active tant que valeur > seuil - hysteresis ; une regle `below`
  est symetrique (active si valeur < seuil, reste active tant que
  valeur < seuil + hysteresis). L'hysteresis evite qu'une valeur qui oscille
  autour du seuil declenche et resolve l'alerte en boucle ;
- le niveau du capteur est la severite maximale de ses regles actives ; la
  regle "responsable" (seuil et direction de l'alerte) est la regle active
  de plus haute severite, et a egalite celle que la valeur depasse le plus ;
- chaque changement de niveau produit un evenement : aucun -> X `raised`,
  warning -> critical `escalated`, critical -> warning `deescalated`,
  X -> aucun `resolved`. Un changement de direction (trop haut -> trop bas
  d'une mesure a l'autre) est une autre alerte : `resolved` puis `raised`.

Le module ne garde aucun etat : `evaluate` recoit l'etat precedent d'un
capteur et retourne le nouveau, avec les evenements a diffuser.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Context, Decimal

from app.data_management.records import sensor_id

WARNING = "warning"
CRITICAL = "critical"
SEVERITIES = (WARNING, CRITICAL)
SEVERITY_RANK = {WARNING: 1, CRITICAL: 2}

ABOVE = "above"
BELOW = "below"
DIRECTIONS = (ABOVE, BELOW)

RAISED = "raised"
ESCALATED = "escalated"
DEESCALATED = "deescalated"
RESOLVED = "resolved"

# Libelles lisibles des topics (les memes que ceux du dashboard)
TOPIC_LABELS = {
    "gridd.obs.environmental.temperature": "Temp\u00e9rature",
    "gridd.obs.environmental.humidity": "Humidit\u00e9",
    "gridd.obs.environmental.co2": "CO\u2082",
    "gridd.obs.acoustic.sound_level": "Niveau sonore",
    "gridd.obs.occupancy.count": "Occupation",
}

# Typographie francaise, celle de l'affichage du dashboard (Intl fr-CA de
# lib/format.ts) : espace insecable U+00A0 pour les milliers, espace fine
# insecable U+202F entre valeur et unite, vrai signe moins. Echappements
# explicites pour qu'un editeur ne les normalise pas.
NBSP = "\u00a0"
NARROW_NBSP = "\u202f"
MINUS = "\u2212"

# Arrondi des nombres : une egalite s'eloigne de zero (17.25 -> 17,3), comme
# Intl.NumberFormat cote dashboard, et non au pair comme le format de Python
# (17,2). La precision couvre la valeur binaire exacte de tout float fini :
# aucun arrondi intermediaire.
_ROUNDING = Context(prec=400, rounding=ROUND_HALF_UP)
# Decimales supplementaires au plus pour distinguer une valeur d'un seuil
_MAX_DECIMALS = 3


def is_number(value: object) -> bool:
    """Nombre fini (int ou float, booleens exclus). Ne leve jamais : un
    entier trop grand pour un float (ex. 10**400) n'est pas un nombre."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def topic_label(topic: str) -> str:
    """Libelle du topic ; repli sur le dernier segment du nom."""
    label = TOPIC_LABELS.get(topic)
    if label:
        return label
    last = topic.rsplit(".", 1)[-1].replace("_", " ")
    return last[:1].upper() + last[1:]


def format_number(value: float, max_decimals: int = 1) -> str:
    """Nombre au format francais : `max_decimals` decimales au plus (zeros
    inutiles retires), virgule decimale, espace insecable pour les milliers,
    egalites arrondies comme le dashboard. Ex. 1120 -> "1 120",
    17.25 -> "17,3", -3.0 -> "-3" (vrai signe moins)."""
    rounded = Decimal(abs(value)).quantize(Decimal(1).scaleb(-max_decimals),
                                           context=_ROUNDING)
    integer, _, decimals = f"{rounded:,f}".partition(".")
    decimals = decimals.rstrip("0")
    text = integer.replace(",", NBSP) + (f",{decimals}" if decimals else "")
    # Une valeur qui s'arrondit a zero ne garde pas son signe (pas de "-0")
    if value < 0 and rounded:
        text = MINUS + text
    return text


def format_quantity(value: float, unit: str, max_decimals: int = 1) -> str:
    """Valeur suivie de son unite ("1 000 ppm") ; unite vide -> valeur seule."""
    number = format_number(value, max_decimals)
    return f"{number}{NARROW_NBSP}{unit}" if unit else number


def format_measured(value: float, unit: str, *limits: float) -> str:
    """Valeur mesuree avec son unite, avec assez de decimales (3 au plus)
    pour ne pas s'ecrire comme une limite (seuil, fin de bande) qu'elle ne
    vaut pas : 26.04 au-dessus de 26 s'ecrit "26,04 °C", et non "26 °C"."""
    decimals = 1
    while decimals < _MAX_DECIMALS and any(
            limit != value
            and format_number(limit, decimals) == format_number(value, decimals)
            for limit in limits):
        decimals += 1
    return format_quantity(value, unit, decimals)


def alert_id(topic: str, node_id: str) -> str:
    """Identifiant d'une alerte : une alerte au plus par topic et capteur."""
    return f"{topic}|{node_id}"


@dataclass(frozen=True)
class AlertRule:
    """Regle d'un topic : seuil franchi dans une direction, avec hysteresis."""
    severity: str
    direction: str
    threshold: float
    hysteresis: float = 0.0

    def is_active(self, value: float, was_active: bool) -> bool:
        """Regle active pour cette valeur. Inactive, elle s'active si la
        valeur depasse strictement le seuil ; active, elle le reste tant que
        la valeur reste au-dela du seuil decale de l'hysteresis."""
        margin = self.hysteresis if was_active else 0.0
        if self.direction == ABOVE:
            return value > self.threshold - margin
        return value < self.threshold + margin

    def excess(self, value: float) -> float:
        """Depassement du seuil par la valeur (negatif en deca)."""
        if self.direction == ABOVE:
            return value - self.threshold
        return self.threshold - value

    @property
    def release(self) -> float:
        """Limite de la bande d'hysteresis : une regle active le reste tant
        que la valeur ne l'a pas atteinte (seuil - hysteresis pour `above`,
        seuil + hysteresis pour `below`)."""
        if self.direction == ABOVE:
            return self.threshold - self.hysteresis
        return self.threshold + self.hysteresis

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "direction": self.direction,
            "threshold": float(self.threshold),
            "hysteresis": float(self.hysteresis),
        }


@dataclass(frozen=True)
class Measurement:
    """Mesure numerique d'un capteur, extraite d'un record."""
    topic: str
    node_id: str
    value: float
    unit: str
    location: str
    timestamp_ms: int


def _location(metadata: object) -> str:
    """Emplacement lisible : libelle de la zone, sinon de l'espace."""
    if not isinstance(metadata, dict):
        return ""
    for key in ("zone", "space"):
        place = metadata.get(key)
        if isinstance(place, dict):
            label = place.get("label")
            if isinstance(label, str) and label:
                return label
    return ""


def measurement_from_record(topic: str, record: dict) -> Measurement | None:
    """Mesure portee par un record, ou None s'il n'en porte pas
    d'exploitable (payload non JSON, valeur non numerique ou absente,
    horodatage absent)."""
    payload = record.get("value")
    if not isinstance(payload, dict):
        return None
    value = payload.get("value")
    timestamp = record.get("timestamp_ms")
    if not is_number(value) or not isinstance(timestamp, int) \
            or isinstance(timestamp, bool):
        return None
    unit = payload.get("unit")
    return Measurement(
        topic=topic,
        node_id=sensor_id(record),
        value=float(value),
        unit=unit if isinstance(unit, str) else "",
        location=_location(payload.get("metadata")),
        timestamp_ms=timestamp,
    )


def alert_message(topic: str, rule: AlertRule, value: float, unit: str) -> str:
    """Message de l'alerte dont `rule` est la regle responsable : texte
    indicatif pour les journaux et les clients de l'API (le dashboard
    compose le sien a partir des champs structures, avec les decimales de
    chaque topic).

    Valeur au-dela du seuil : "CO2 au-dessus de 1 000 ppm (1 120 ppm)".
    Valeur revenue en deca du seuil, regle maintenue par l'hysteresis : le
    message ne pretend plus que le seuil est franchi et donne la limite de
    la bande, ex. "CO2 a 960 ppm (seuil 1 000 ppm), alerte maintenue
    jusqu'a 950 ppm" ("niveau critique maintenu" pour une regle critical :
    en sortant de sa bande, l'alerte peut redescendre en warning). La valeur
    garde assez de decimales pour ne jamais s'ecrire comme le seuil."""
    label = topic_label(topic)
    threshold = format_quantity(rule.threshold, unit)
    if rule.excess(value) > 0:
        where = "au-dessus de" if rule.direction == ABOVE else "en dessous de"
        measured = format_measured(value, unit, rule.threshold)
        return f"{label} {where} {threshold} ({measured})"
    held = ("niveau critique maintenu" if rule.severity == CRITICAL
            else "alerte maintenue")
    measured = format_measured(value, unit, rule.threshold, rule.release)
    return (f"{label} \u00e0 {measured} (seuil {threshold}),"
            f" {held} jusqu\u2019\u00e0 {format_quantity(rule.release, unit)}")


@dataclass(frozen=True)
class Alert:
    """Alerte active d'un capteur (forme de l'API : `to_dict`). Severite,
    direction, seuil et hysteresis sont ceux de la regle responsable."""
    topic: str
    node_id: str
    severity: str
    direction: str
    threshold: float
    hysteresis: float
    value: float
    unit: str
    location: str
    since_ms: int
    updated_ms: int
    message: str

    @property
    def id(self) -> str:
        return alert_id(self.topic, self.node_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "node_id": self.node_id,
            "severity": self.severity,
            "direction": self.direction,
            "threshold": float(self.threshold),
            "hysteresis": float(self.hysteresis),
            "value": float(self.value),
            "unit": self.unit,
            "location": self.location,
            "since_ms": self.since_ms,
            "updated_ms": self.updated_ms,
            "message": self.message,
        }


@dataclass(frozen=True)
class AlertEvent:
    """Changement de niveau d'une alerte. Pour `resolved`, `alert` est l'etat
    juste avant la resolution (message compris), dont seules la valeur et
    l'horodatage sont ceux de la mesure qui resout (contrat de l'API)."""
    kind: str
    at_ms: int
    alert: Alert

    def to_dict(self) -> dict:
        return {"kind": self.kind, "at_ms": self.at_ms,
                "alert": self.alert.to_dict()}


@dataclass(frozen=True)
class SensorState:
    """Etat d'alerte d'un capteur : regles actives (indices dans la liste
    des regles du topic) et alerte en cours (None si aucune)."""
    active_rules: frozenset[int] = frozenset()
    alert: Alert | None = None


def _resolved(alert: Alert, measurement: Measurement) -> AlertEvent:
    """Evenement de resolution de `alert` par `measurement` : l'etat juste
    avant la resolution, dont seules la valeur et l'horodatage changent."""
    return AlertEvent(RESOLVED, measurement.timestamp_ms, replace(
        alert, value=measurement.value, updated_ms=measurement.timestamp_ms))


def evaluate(rules: Sequence[AlertRule], measurement: Measurement,
             state: SensorState = SensorState(),
             ) -> tuple[SensorState, list[AlertEvent]]:
    """Evalue une mesure d'un capteur ; retourne son nouvel etat et les
    evenements produits (aucun si le niveau ne change pas : l'alerte en
    cours est alors seulement mise a jour avec la derniere mesure)."""
    value, at_ms = measurement.value, measurement.timestamp_ms
    active = frozenset(i for i, rule in enumerate(rules)
                       if rule.is_active(value, i in state.active_rules))
    previous = state.alert

    if not active:
        events = [] if previous is None else [_resolved(previous, measurement)]
        return SensorState(), events

    # Regle responsable : plus haute severite, puis plus grand depassement,
    # puis premiere dans l'ordre du fichier
    index = max(active, key=lambda i: (SEVERITY_RANK[rules[i].severity],
                                       rules[i].excess(value), -i))
    rule = rules[index]
    # Meme direction : c'est la meme alerte, qui garde son debut
    continued = previous is not None and previous.direction == rule.direction
    alert = Alert(
        topic=measurement.topic,
        node_id=measurement.node_id,
        severity=rule.severity,
        direction=rule.direction,
        threshold=rule.threshold,
        hysteresis=rule.hysteresis,
        value=value,
        unit=measurement.unit,
        location=measurement.location,
        since_ms=previous.since_ms if continued else at_ms,
        updated_ms=at_ms,
        message=alert_message(measurement.topic, rule, value, measurement.unit),
    )

    events: list[AlertEvent] = []
    if previous is None:
        events.append(AlertEvent(RAISED, at_ms, alert))
    elif not continued:
        events.append(_resolved(previous, measurement))
        events.append(AlertEvent(RAISED, at_ms, alert))
    else:
        before = SEVERITY_RANK[previous.severity]
        after = SEVERITY_RANK[rule.severity]
        if after > before:
            events.append(AlertEvent(ESCALATED, at_ms, alert))
        elif after < before:
            events.append(AlertEvent(DEESCALATED, at_ms, alert))
    return SensorState(active, alert), events
