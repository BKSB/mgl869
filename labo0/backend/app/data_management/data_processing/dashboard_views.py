"""Vues du dashboard pretes a afficher (libelles, nombres formates, tri,
comptes, etats) : le frontend n'applique aucune regle metier. Logique pure.

Parametres d'une vue (JSON du client ou query string) :
  view=rooms   room=<id>        range=15m|1h|24h
  view=metric  metric=<id>      range=15m|1h|24h   sort=severity|room|value
  view=alerts  filter=active|acknowledged|resolved|all
  view=chart   metric=<id> sensor=<id> range=24h|7d|30d from=<ms> to=<ms>
Valeur absente ou inconnue : defaut (premiere piece, premier topic...)."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

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
    HOUR_MS,
    NO_PLACE_ID,
    UNKNOWN_PLACE,
    Bucket,
    Place,
    SensorTwin,
    add_to_bucket,
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

# Unites des payloads gridd -> affichage ; "person" : la valeur seule suffit
UNIT_LABELS = {"C": "°C", "degC": "°C", "person": "", "persons": ""}
# Metrique sommee dans l'en-tete (« n personnes dans le local »)
PEOPLE_METRIC = "occupancy"

# Plage du graphe plein ecran : libelle, duree, case d'agregation, titre de
# l'apercu. Au-dela de 24 h, les cases sont les agregats horaires du jumeau.
CHART_RANGES = {
    "24h": ("24 h", 24 * HOUR_MS, 10 * 60_000, "24 dernières heures"),
    "7d": ("7 j", 7 * 24 * HOUR_MS, HOUR_MS, "7 derniers jours"),
    "30d": ("30 j", 30 * 24 * HOUR_MS, HOUR_MS, "30 derniers jours"),
}
DEFAULT_CHART_RANGE = "30d"
MIN_ZOOM_MS = 60_000


def _unit(raw: str) -> str:
    return UNIT_LABELS.get(raw, raw)


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
    deja a cote de la valeur), `label` pour la ligne du graphe."""
    return [{
        "severity": rule.severity,
        "direction": rule.direction,
        "value": rule.threshold,
        "text": f"{SEVERITY_CODES[rule.severity]} {_symbol(rule.direction)} "
                f"{format_quantity(rule.threshold, unit)}",
        "short": f"{SEVERITY_CODES[rule.severity]} {_symbol(rule.direction)} "
                 f"{format_number(rule.threshold)}",
        "label": f"Seuil {STATUS_LABELS[rule.severity].lower()} "
                 f"{format_number(rule.threshold)}",
    } for rule in rules]


def _value_status(rules: Sequence[AlertRule], value: float) -> str:
    """Severite des regles franchies par une valeur (sans hysteresis)."""
    crossed = [r.severity for r in rules if r.is_active(value, False)]
    return max(crossed, key=STATUS_RANK.__getitem__, default=NORMAL)


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
    unit = _unit(sensor.unit)
    stats = ""
    if values:
        stats = (f"{range_label} : min {format_fixed(min(values), metric.decimals)}"
                 f" · max {format_fixed(max(values), metric.decimals)}")
    return {
        "id": sensor.id,
        "metric": metric.id,
        "label": metric.label,
        "unit": unit,
        "room": _place_dict(sensor.place),
        "value_text": format_fixed(sensor.value, metric.decimals),
        "status": status,
        "status_label": STATUS_LABELS[status],
        "updated_ms": sensor.updated_ms,
        "thresholds": _thresholds(ctx.rules.get(sensor.topic, ()), unit),
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
    """Pire etat et nombre de capteurs dans cet etat."""
    statuses = [ctx.status(s) for s in sensors]
    worst = max(statuses, key=STATUS_RANK.__getitem__)
    return worst, statuses.count(worst)


def _room_detail(ctx: Context, place: Place, sensors: list[SensorTwin],
                 range_id: str) -> dict:
    status, at_worst = _room_status(ctx, sensors)
    label = STATUS_LABELS[status]
    if status != NORMAL:
        label += f" · {_plural(at_worst, 'capteur')}"
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
    # Capteurs sans piece (ex. camera d'occupation) : hors menu, mais la
    # « piece » reste accessible par son id (tuile Par capteur, Voir la piece)
    listed = [r for r in rooms if r[0].id != NO_PLACE_ID]
    wanted = params.get("room")
    if wanted:
        selected = next((r for r in rooms if r[0].id == wanted), None)
    else:
        selected = listed[0] if listed else None
    range_id = _choice(params, "range", RANGES, DEFAULT_RANGE)
    return {
        "view": "rooms",
        "rooms": [{**_place_dict(place), "status": _room_status(ctx, sensors)[0]}
                  for place, sensors in listed],
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
    # Occupation : resumee dans l'en-tete (people), pas d'onglet
    topics = [t for t in ctx.topics if metric_for(t).id != PEOPLE_METRIC]
    tabs = [{"id": metric_for(t).id, "label": metric_for(t).label}
            for t in topics]
    wanted = params.get("metric")
    topic = next((t for t in topics if metric_for(t).id == wanted), None) \
        or (topics[0] if topics else None)
    if topic is None:
        return {"view": "metric", "metrics": tabs, "metric": None}
    metric = metric_for(topic)
    range_id = _choice(params, "range", RANGES, DEFAULT_RANGE)
    sort = _choice(params, "sort", SORTS, DEFAULT_SORT)
    sensors = sorted((s for s in ctx.sensors if s.topic == topic),
                     key=_sort_key(ctx, sort))
    unit = _unit(next((s.unit for s in sensors if s.unit), ""))
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
    return format_measured(alert.value, _unit(alert.unit), alert.threshold,
                           decimals=metric_for(alert.topic).decimals)


def _threshold_text(alert: Alert) -> str:
    return (f"{SEVERITY_CODES[alert.severity]} {_symbol(alert.direction)} "
            f"{format_quantity(alert.threshold, _unit(alert.unit))}")


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
        "threshold_text": _threshold_text(alert),
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


# --- Graphe plein ecran ------------------------------------------------------

def _int_param(params: Mapping, key: str) -> int | None:
    value = params.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None


def _zoom(params: Mapping, from_ms: int, to_ms: int) -> tuple[int, int] | None:
    """Fenetre [from, to] bornee a la plage ; None si absente, trop etroite
    ou egale a la plage."""
    a, b = _int_param(params, "from"), _int_param(params, "to")
    if a is None or b is None:
        return None
    a, b = max(a, from_ms), min(b, to_ms)
    if b - a < MIN_ZOOM_MS or (a, b) == (from_ms, to_ms):
        return None
    return a, b


def _buckets(sensor: SensorTwin, from_ms: int,
             bucket_ms: int) -> list[tuple[int, Bucket]]:
    """Cases de la plage : agregats horaires du jumeau, ou points bruts
    regroupes (plage 24 h)."""
    if bucket_ms >= HOUR_MS:
        return sensor.hours_since(from_ms)
    buckets: dict[int, Bucket] = {}
    for t, v in sensor.window(from_ms):
        start = t - t % bucket_ms
        buckets[start] = add_to_bucket(buckets.get(start), v)
    return sorted(buckets.items())


def _alert_counts(ctx: Context, sensor: SensorTwin, a: int, b: int) -> list[dict]:
    """Episodes d'alerte du capteur touchant la fenetre (evenements recents
    et alerte active), par severite maximale atteinte."""
    key = (sensor.topic, sensor.id)
    episodes: dict[int, str] = {}

    def note(alert: Alert, at_ms: int) -> None:
        if (alert.topic, alert.node_id) == key and a <= at_ms <= b:
            episodes[alert.since_ms] = max(
                episodes.get(alert.since_ms, alert.severity), alert.severity,
                key=STATUS_RANK.__getitem__)

    for event in ctx.recent:
        note(event.alert, event.at_ms)
    active = ctx.alerts.get(key)
    if active:
        note(active, active.updated_ms)
    counts = Counter(episodes.values())
    items = [{"status": s, "text": f"{counts[s]} {STATUS_LABELS[s].lower()}"}
             for s in (WARNING, CRITICAL) if counts[s]]
    return items or [{"status": NORMAL, "text": "aucune"}]


@dataclass(frozen=True)
class _ChartData:
    sensor: SensorTwin
    range_id: str
    span: tuple[int, int]
    zoom: tuple[int, int] | None
    buckets: list[tuple[int, Bucket]]

    @property
    def window(self) -> tuple[int, int]:
        return self.zoom or self.span

    def visible(self) -> list[tuple[int, Bucket]]:
        a, b = self.window
        return [(t, bk) for t, bk in self.buckets if a <= t <= b]


def _chart_data(ctx: Context, params: Mapping) -> _ChartData | None:
    metric_id, sensor_id = params.get("metric"), params.get("sensor")
    topic = next((t for t in ctx.topics if metric_for(t).id == metric_id), None)
    sensor = next((s for s in ctx.sensors
                   if s.topic == topic and s.id == sensor_id), None)
    if sensor is None:
        return None
    range_id = _choice(params, "range", CHART_RANGES, DEFAULT_CHART_RANGE)
    _, span_ms, bucket_ms, _ = CHART_RANGES[range_id]
    to_ms = ctx.now_ms
    from_ms = to_ms - span_ms
    return _ChartData(sensor, range_id, (from_ms, to_ms),
                      _zoom(params, from_ms, to_ms),
                      _buckets(sensor, from_ms, bucket_ms))


def _chart_stats(ctx: Context, data: _ChartData, rules: Sequence[AlertRule],
                 decimals: int) -> dict | None:
    visible = data.visible()
    if not visible:
        return None
    count = sum(bk[0] for _, bk in visible)
    total = sum(bk[1] for _, bk in visible)
    low = min(bk[2] for _, bk in visible)
    high = max(bk[3] for _, bk in visible)
    return {
        "scope": "zoom" if data.zoom else CHART_RANGES[data.range_id][0],
        "min": {"text": format_fixed(low, decimals),
                "status": _value_status(rules, low)},
        "max": {"text": format_fixed(high, decimals),
                "status": _value_status(rules, high)},
        "mean": {"text": format_fixed(total / count, decimals)},
        "alerts": _alert_counts(ctx, data.sensor, *data.window),
    }


def chart_view(ctx: Context, params: Mapping) -> dict:
    data = _chart_data(ctx, params)
    if data is None:
        return {"view": "chart", "chart": None}
    sensor = data.sensor
    metric = metric_for(sensor.topic)
    unit = _unit(sensor.unit)
    rules = ctx.rules.get(sensor.topic, ())
    range_label, _, _, overview_label = CHART_RANGES[data.range_id]
    query = {"metric": metric.id, "sensor": sensor.id, "range": data.range_id}
    if data.zoom:
        query["from"], query["to"] = data.zoom
    return {
        "view": "chart",
        "chart": {
            "metric": metric.id,
            "label": metric.label,
            "unit": unit,
            "sensor_id": sensor.id,
            "room": _place_dict(sensor.place),
            "value_text": format_fixed(sensor.value, metric.decimals),
            "status": ctx.status(sensor),
            "updated_ms": sensor.updated_ms,
            "range": data.range_id,
            "range_label": range_label,
            "ranges": [{"id": k, "label": v[0]} for k, v in CHART_RANGES.items()],
            "overview_label": overview_label,
            "span": list(data.span),
            "zoom": list(data.zoom) if data.zoom else None,
            "thresholds": _thresholds(rules, unit),
            # [debut de case, moyenne, etat, moyenne formatee]
            "series": [[t, bk[1] / bk[0], _value_status(rules, bk[1] / bk[0]),
                        format_fixed(bk[1] / bk[0], metric.decimals)]
                       for t, bk in data.buckets],
            "stats": _chart_stats(ctx, data, rules, metric.decimals),
            "csv_url": f"/api/chart.csv?{urlencode(query)}",
        },
    }


def chart_csv(ctx: Context, params: Mapping) -> tuple[str, str] | None:
    """Cases affichees (fenetre de zoom comprise) : (nom de fichier, CSV)."""
    data = _chart_data(ctx, params)
    if data is None:
        return None
    lines = ["timestamp_ms,datetime_utc,mean,min,max,count"]
    for t, (count, total, low, high) in data.visible():
        when = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        lines.append(f"{t},{when.isoformat(timespec='minutes')},"
                     f"{round(total / count, 3)},{low},{high},{int(count)}")
    name = f"{metric_for(data.sensor.topic).id}-{data.sensor.id}-{data.range_id}.csv"
    return name, "\n".join(lines) + "\n"


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
                f"{format_quantity(alert.threshold, _unit(alert.unit))}",
        "alert_id": alert.id,
        "room_id": place.id,
    }


# --- Enveloppe ---------------------------------------------------------------

VIEWS = {"rooms": rooms_view, "metric": metric_view, "alerts": alerts_view,
         "chart": chart_view}


def _site(ctx: Context) -> str:
    """« Local A-1540 » (metadata.space), sinon le batiment, sinon vide."""
    spaces = sorted({s.place.space for s in ctx.sensors if s.place.space})
    if spaces:
        return ("Local " if len(spaces) == 1 else "Locaux ") + ", ".join(spaces)
    return ", ".join(sorted({s.place.building for s in ctx.sensors
                             if s.place.building}))


def _people(ctx: Context) -> dict | None:
    """Somme des capteurs d'occupation, datee de la mesure la plus recente."""
    sensors = [s for s in ctx.sensors
               if metric_for(s.topic).id == PEOPLE_METRIC]
    if not sensors:
        return None
    total = round(sum(s.value for s in sensors))
    return {
        "count_text": format_fixed(total, 0),
        "label": f"personne{'s' if total > 1 else ''} dans le local",
        "updated_ms": max(s.updated_ms for s in sensors),
    }


def render(ctx: Context, params: Mapping) -> dict:
    """En-tete commun (local, personnes presentes, badge des alertes non
    acquittees, plages) et vue."""
    view = _choice(params, "view", VIEWS, "rooms")
    return {
        "type": "view",
        "site": _site(ctx),
        "people": _people(ctx),
        "alerts_enabled": ctx.alerts_enabled,
        "alerts_active": sum(1 for a in ctx.alerts.values()
                             if a.acknowledged_ms is None),
        "ranges": [{"id": k, "label": v[0]} for k, v in RANGES.items()],
        **VIEWS[view](ctx, params),
    }
