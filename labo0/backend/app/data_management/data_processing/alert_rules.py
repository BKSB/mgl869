"""Evaluation des regles d'alerte : logique pure, sans asyncio ni I/O."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.data_management.data_processing.formatting import (
    format_measured,
    format_quantity,
    topic_label,
)
from app.data_management.records import sensor_id

# Contrat de l'API et de alerts.yaml
Severity = Literal["warning", "critical"]
Direction = Literal["above", "below"]
EventKind = Literal["raised", "escalated", "deescalated", "resolved",
                    "acknowledged"]

WARNING: Severity = "warning"
CRITICAL: Severity = "critical"
SEVERITIES: tuple[Severity, ...] = (WARNING, CRITICAL)
SEVERITY_RANK: dict[Severity, int] = {WARNING: 1, CRITICAL: 2}

ABOVE: Direction = "above"
BELOW: Direction = "below"
DIRECTIONS: tuple[Direction, ...] = (ABOVE, BELOW)

RAISED: EventKind = "raised"
ESCALATED: EventKind = "escalated"
DEESCALATED: EventKind = "deescalated"
RESOLVED: EventKind = "resolved"
ACKNOWLEDGED: EventKind = "acknowledged"


def is_number(value: object) -> bool:
    """Nombre fini, booleens exclus ; 10**400 donne faux, sans lever."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class AlertRule:
    severity: Severity
    direction: Direction
    threshold: float
    hysteresis: float = 0.0

    def is_active(self, value: float, was_active: bool) -> bool:
        """S'active strictement au-dela du seuil ; se relache a `release`."""
        margin = self.hysteresis if was_active else 0.0
        if self.direction == ABOVE:
            return value > self.threshold - margin
        return value < self.threshold + margin

    def excess(self, value: float) -> float:
        """Positif au-dela du seuil, negatif en deca."""
        if self.direction == ABOVE:
            return value - self.threshold
        return self.threshold - value

    @property
    def release(self) -> float:
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
    topic: str
    node_id: str
    value: float
    unit: str
    location: str
    timestamp_ms: int


def _location(metadata: object) -> str:
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
    """Texte indicatif (journaux, API) ; le dashboard compose le sien. Ex.
    "CO2 au-dessus de 1 000 ppm (1 120 ppm)" ; maintenue par l'hysteresis :
    "CO2 a 960 ppm (seuil 1 000 ppm), alerte maintenue jusqu'a 950 ppm"."""
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
    """Severite, direction, seuil, hysteresis : de la regle responsable."""
    topic: str
    node_id: str
    severity: Severity
    direction: Direction
    threshold: float
    hysteresis: float
    value: float
    unit: str
    location: str
    since_ms: int
    updated_ms: int
    message: str
    # Acquittement (AlertService.acknowledge), conserve jusqu'a la resolution
    acknowledged_by: str = ""
    acknowledged_ms: int | None = None

    @property
    def id(self) -> str:
        """Une alerte au plus par topic et capteur."""
        return f"{self.topic}|{self.node_id}"

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
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_ms": self.acknowledged_ms,
        }


@dataclass(frozen=True)
class AlertEvent:
    """`resolved` : `alert` est l'etat d'avant la resolution, sauf valeur et
    horodatage, ceux de la mesure qui resout (contrat de l'API)."""
    kind: EventKind
    at_ms: int
    alert: Alert

    def to_dict(self) -> dict:
        return {"kind": self.kind, "at_ms": self.at_ms,
                "alert": self.alert.to_dict()}


@dataclass(frozen=True)
class SensorState:
    """active_rules : indices dans la liste des regles du topic."""
    active_rules: frozenset[int] = frozenset()
    alert: Alert | None = None


def _resolved(alert: Alert, measurement: Measurement) -> AlertEvent:
    return AlertEvent(RESOLVED, measurement.timestamp_ms, replace(
        alert, value=measurement.value, updated_ms=measurement.timestamp_ms))


def evaluate(rules: Sequence[AlertRule], measurement: Measurement,
             state: SensorState = SensorState(),
             ) -> tuple[SensorState, list[AlertEvent]]:
    """Niveau inchange : pas d'evenement, l'alerte est seulement rafraichie."""
    value, at_ms = measurement.value, measurement.timestamp_ms
    active = frozenset(i for i, rule in enumerate(rules)
                       if rule.is_active(value, i in state.active_rules))
    previous = state.alert

    if not active:
        events = [] if previous is None else [_resolved(previous, measurement)]
        return SensorState(), events

    # Regle responsable : severite, puis depassement, puis ordre du fichier
    index = max(active, key=lambda i: (SEVERITY_RANK[rules[i].severity],
                                       rules[i].excess(value), -i))
    rule = rules[index]
    # Meme direction : meme alerte (meme debut) ; sinon resolved puis raised
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
        acknowledged_by=previous.acknowledged_by if continued else "",
        acknowledged_ms=previous.acknowledged_ms if continued else None,
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
