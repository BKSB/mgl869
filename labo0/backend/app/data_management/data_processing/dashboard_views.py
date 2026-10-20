"""Vues du dashboard pretes a afficher (libelles, nombres formates, tri,
comptes, etats) : le frontend n'applique aucune regle metier. Logique pure.

Parametres d'une vue (JSON du client ou query string) :
  view=rooms   room=<id>        range=15m|1h|24h
  view=metric  metric=<id>      range=15m|1h|24h   sort=severity|room|value
  view=alerts  filter=active|acknowledged|resolved|all
Valeur absente ou inconnue : defaut (premiere piece, premier topic...)."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.data_management.data_processing.alert_rules import (
    ABOVE,
    CRITICAL,
    RESOLVED,
    SEVERITY_RANK,
    WARNING,
    Alert,
    AlertEvent,
    AlertRule,
)
from app.data_management.data_processing.digital_twin import (
    NO_PLACE_ID,
    UNKNOWN_PLACE,
    Place,
    SensorTwin,
)
from app.data_management.data_processing.formatting import (
    format_fixed,
    format_measured,
    format_number,
    format_quantity,
    metric_for,
)

NORMAL = "normal"
STATUS_LABELS = {NORMAL: "Normal", WARNING: "Warning", CRITICAL: "Erreur"}
STATUS_RANK = {NORMAL: 0, **SEVERITY_RANK}
SEVERITY_CODES = {WARNING: "W", CRITICAL: "E"}

# id -> (libelle, duree)
RANGES = {"15m": ("15 min", 15 * 60_000), "1h": ("1 h", 3_600_000),
          "24h": ("24 h", 24 * 3_600_000)}
DEFAULT_RANGE = "1h"
# Points par sparkline : au-dela, echantillonnage regulier (dernier point garde)
MAX_POINTS = 120

SORTS = {"severity": "Sévérité", "room": "Pièce", "value": "Valeur"}
DEFAULT_SORT = "severity"

ACTIVE, ACKNOWLEDGED, RESOLVED_STATE = "active", "acknowledged", "resolved"
STATE_RANK = {ACTIVE: 0, ACKNOWLEDGED: 1, RESOLVED_STATE: 2}
FILTERS = {ACTIVE: "Actives", ACKNOWLEDGED: "Acquittées",
           RESOLVED_STATE: "Résolues", "all": "Toutes"}
DEFAULT_FILTER = ACTIVE


@dataclass(frozen=True)
class Context:
    """Etat lu au moment du rendu."""
    sensors: Sequence[SensorTwin]
    # Alertes actives par (topic, capteur)
    alerts: Mapping[tuple[str, str], Alert]
    # Evenements recents, le plus recent d'abord
    recent: Sequence[AlertEvent]
    rules: Mapping[str, Sequence[AlertRule]]
    # Ordre des onglets et des tuiles
    topics: Sequence[str]
    alerts_enabled: bool
    now_ms: int

    def status(self, sensor: SensorTwin) -> str:
        alert = self.alerts.get((sensor.topic, sensor.id))
        return alert.severity if alert else NORMAL


def _choice(params: Mapping, key: str, options: Mapping, default: str) -> str:
    value = params.get(key)
    return value if isinstance(value, str) and value in options else default


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count > 1 else ''}"


def _symbol(direction: str) -> str:
    return ">" if direction == ABOVE else "<"


def _place_dict(place: Place) -> dict:
    return {"id": place.id, "name": place.name, "floor": place.floor}


def _fallback_place(alert: Alert) -> Place:
    """Capteur inconnu du jumeau : la location de l'alerte nomme la piece."""
    return Place(NO_PLACE_ID, alert.location) if alert.location else UNKNOWN_PLACE


def _thresholds(rules: Sequence[AlertRule], unit: str) -> list[dict]:
    """`text` avec unite (en-tete), `short` sans (pied de tuile, l'unite est
    deja a cote de la valeur)."""
    return [{
        "severity": rule.severity,
        "value": rule.threshold,
        "text": f"{SEVERITY_CODES[rule.severity]} {_symbol(rule.direction)} "
                f"{format_quantity(rule.threshold, unit)}",
        "short": f"{SEVERITY_CODES[rule.severity]} {_symbol(rule.direction)} "
                 f"{format_number(rule.threshold)}",
    } for rule in rules]


def _downsample(points: Sequence[tuple[int, float]]) -> list[list]:
    if len(points) > MAX_POINTS:
        step = len(points) / MAX_POINTS
        points = [points[int(i * step)] for i in range(MAX_POINTS - 1)] \
            + [points[-1]]
    return [[t, v] for t, v in points]


def _tile(ctx: Context, sensor: SensorTwin, range_id: str) -> dict:
    metric = metric_for(sensor.topic)
    range_label, span_ms = RANGES[range_id]
    points = sensor.window(ctx.now_ms - span_ms)
    values = [v for _, v in points]
    status = ctx.status(sensor)
    stats = ""
    if values:
        stats = (f"{range_label} : min {format_fixed(min(values), metric.decimals)}"
                 f" · max {format_fixed(max(values), metric.decimals)}")
    return {
        "id": sensor.id,
        "metric": metric.id,
        "label": metric.label,
        "unit": sensor.unit,
        "room": _place_dict(sensor.place),
        "value_text": format_fixed(sensor.value, metric.decimals),
        "status": status,
        "status_label": STATUS_LABELS[status],
        "updated_ms": sensor.updated_ms,
        "thresholds": _thresholds(ctx.rules.get(sensor.topic, ()), sensor.unit),
        "points": _downsample(points),
        "stats_text": stats,
    }


# --- Par piece ---------------------------------------------------------------

def _rooms(ctx: Context) -> list[tuple[Place, list[SensorTwin]]]:
    """Capteurs par piece (id) ; la metadonnee la plus recente nomme la piece.
    Pieces par etage puis nom, capteurs dans l'ordre des topics."""
    groups: dict[str, list[SensorTwin]] = {}
    for sensor in sorted(ctx.sensors, key=lambda s: s.updated_ms):
        groups.setdefault(sensor.place.id, []).append(sensor)
    order = {topic: i for i, topic in enumerate(ctx.topics)}
    rooms = []
    for sensors in groups.values():
        place = sensors[-1].place
        sensors.sort(key=lambda s: (order.get(s.topic, len(order)), s.id))
        rooms.append((place, sensors))
    rooms.sort(key=lambda room: (room[0].floor.casefold(),
                                 room[0].name.casefold()))
    return rooms


def _room_status(ctx: Context, sensors: Sequence[SensorTwin]) -> tuple[str, int]:
    """Pire etat et nombre de capteurs en alerte."""
    statuses = [ctx.status(s) for s in sensors]
    worst = max(statuses, key=STATUS_RANK.__getitem__)
    return worst, sum(1 for s in statuses if s != NORMAL)


def _room_detail(ctx: Context, place: Place, sensors: list[SensorTwin],
                 range_id: str) -> dict:
    status, in_alert = _room_status(ctx, sensors)
    label = STATUS_LABELS[status]
    if in_alert:
        label += f" · {_plural(in_alert, 'capteur')}"
    return {
        **_place_dict(place),
        "building": place.building,
        "status": status,
        "status_label": label,
        "summary": _plural(len(sensors), "capteur"),
        "last_ms": max(s.updated_ms for s in sensors),
        "range": range_id,
        "sensors": [_tile(ctx, s, range_id) for s in sensors],
    }


def rooms_view(ctx: Context, params: Mapping) -> dict:
    rooms = _rooms(ctx)
    wanted = params.get("room")
    if wanted:
        selected = next((r for r in rooms if r[0].id == wanted), None)
    else:
        selected = rooms[0] if rooms else None
    range_id = _choice(params, "range", RANGES, DEFAULT_RANGE)
    return {
        "view": "rooms",
        "rooms": [{**_place_dict(place), "status": _room_status(ctx, sensors)[0]}
                  for place, sensors in rooms],
        "room": _room_detail(ctx, *selected, range_id) if selected else None,
    }


# --- Par capteur -------------------------------------------------------------

def _sort_key(ctx: Context, sort: str) -> Callable[[SensorTwin], tuple]:
    def severity(s: SensorTwin) -> tuple:
        return (-STATUS_RANK[ctx.status(s)], s.place.name.casefold(), s.id)

    def room(s: SensorTwin) -> tuple:
        return (s.place.floor.casefold(), s.place.name.casefold(), s.id)

    def value(s: SensorTwin) -> tuple:
        return (-s.value, s.id)

    return {"severity": severity, "room": room, "value": value}[sort]


def metric_view(ctx: Context, params: Mapping) -> dict:
    tabs = [{"id": metric_for(t).id, "label": metric_for(t).label}
            for t in ctx.topics]
    wanted = params.get("metric")
    topic = next((t for t in ctx.topics if metric_for(t).id == wanted), None) \
        or (ctx.topics[0] if ctx.topics else None)
    if topic is None:
        return {"view": "metric", "metrics": tabs, "metric": None}
    metric = metric_for(topic)
    range_id = _choice(params, "range", RANGES, DEFAULT_RANGE)
    sort = _choice(params, "sort", SORTS, DEFAULT_SORT)
    sensors = sorted((s for s in ctx.sensors if s.topic == topic),
                     key=_sort_key(ctx, sort))
    unit = next((s.unit for s in sensors if s.unit), "")
    counts = Counter(ctx.status(s) for s in sensors)
    return {
        "view": "metric",
        "metrics": tabs,
        "metric": {
            "id": metric.id,
            "label": metric.label,
            "unit": unit,
            "thresholds": _thresholds(ctx.rules.get(topic, ()), unit),
            "summary": _plural(len(sensors), "capteur"),
            "counts": [{"status": status, "text": f"{counts[status]} {label.lower()}"}
                       for status, label in STATUS_LABELS.items()],
            "range": range_id,
            "sort": sort,
            "sorts": [{"id": k, "label": v} for k, v in SORTS.items()],
            "sensors": [_tile(ctx, s, range_id) for s in sensors],
        },
    }


# --- Alertes -----------------------------------------------------------------

def _measured(alert: Alert) -> str:
    return format_measured(alert.value, alert.unit, alert.threshold,
                           decimals=metric_for(alert.topic).decimals)


def _alert_row(alert: Alert, place: Place, state: str,
               state_ms: int | None) -> dict:
    if state == ACTIVE:
        state_label = "Active"
    elif state == ACKNOWLEDGED:
        state_label = "Acquittée" + (f" · {alert.acknowledged_by}"
                                    if alert.acknowledged_by else "")
    else:
        state_label = "Résolue"
    return {
        "id": alert.id,
        "key": f"{alert.id}|{alert.since_ms}",
        "severity": alert.severity,
        "severity_label": STATUS_LABELS[alert.severity],
        "room": _place_dict(place),
        "metric_label": metric_for(alert.topic).label,
        "sensor_id": alert.node_id,
        "value_text": _measured(alert),
        "threshold_text": f"{SEVERITY_CODES[alert.severity]} "
                          f"{_symbol(alert.direction)} "
                          f"{format_quantity(alert.threshold, alert.unit)}",
        "since_ms": alert.since_ms,
        "state": state,
        "state_label": state_label,
        "state_ms": state_ms,
        "can_ack": state == ACTIVE,
    }


def alerts_view(ctx: Context, params: Mapping) -> dict:
    places = {(s.topic, s.id): s.place for s in ctx.sensors}

    def row(alert: Alert, state: str, state_ms: int | None) -> dict:
        place = places.get((alert.topic, alert.node_id)) or _fallback_place(alert)
        return _alert_row(alert, place, state, state_ms)

    rows = [row(a, ACKNOWLEDGED if a.acknowledged_ms is not None else ACTIVE,
                a.acknowledged_ms) for a in ctx.alerts.values()]
    rows += [row(e.alert, RESOLVED_STATE, e.at_ms)
             for e in ctx.recent if e.kind == RESOLVED]
    # Actives, acquittees puis resolues ; les plus recentes d'abord
    rows.sort(key=lambda r: (STATE_RANK[r["state"]],
                             -(r["state_ms"] if r["state"] == RESOLVED_STATE
                               else r["since_ms"])))
    counts = Counter(r["state"] for r in rows)
    severities = Counter(r["severity"] for r in rows if r["state"] == ACTIVE)
    filter_id = _choice(params, "filter", FILTERS, DEFAULT_FILTER)
    return {
        "view": "alerts",
        "filter": filter_id,
        "filters": [{"id": k, "label": v,
                     "count": None if k == "all" else counts[k]}
                    for k, v in FILTERS.items()],
        "summary": f"{_plural(counts[ACTIVE], 'active')} · "
                   f"{_plural(severities[CRITICAL], 'erreur')}, "
                   f"{severities[WARNING]} warning",
        "alerts": [r for r in rows
                   if filter_id == "all" or r["state"] == filter_id],
    }


def toast(event: AlertEvent, place: Place | None) -> dict:
    """Notification d'une alerte declenchee ou escaladee."""
    alert = event.alert
    place = place or _fallback_place(alert)
    label = STATUS_LABELS[alert.severity]
    return {
        "type": "toast",
        "id": f"{alert.id}|{event.at_ms}|{event.kind}",
        "severity": alert.severity,
        "severity_label": label,
        "at_ms": event.at_ms,
        "title": f"{metric_for(alert.topic).label} · {place.name}",
        "value_text": _measured(alert),
        "text": f"{_symbol(alert.direction)} seuil {label.lower()} "
                f"{format_quantity(alert.threshold, alert.unit)}",
        "alert_id": alert.id,
        "room_id": place.id,
    }


# --- Enveloppe ---------------------------------------------------------------

VIEWS = {"rooms": rooms_view, "metric": metric_view, "alerts": alerts_view}


def render(ctx: Context, params: Mapping) -> dict:
    """En-tete commun (site, badge des alertes non acquittees, plages) et vue."""
    view = _choice(params, "view", VIEWS, "rooms")
    return {
        "type": "view",
        "site": ", ".join(sorted({s.place.building for s in ctx.sensors
                                  if s.place.building})),
        "alerts_enabled": ctx.alerts_enabled,
        "alerts_active": sum(1 for a in ctx.alerts.values()
                             if a.acknowledged_ms is None),
        "ranges": [{"id": k, "label": v[0]} for k, v in RANGES.items()],
        **VIEWS[view](ctx, params),
    }
