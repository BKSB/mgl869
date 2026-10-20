"""Libelles des topics et formatage fr-CA des nombres (messages d'alerte,
vues du dashboard)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal


@dataclass(frozen=True)
class Metric:
    """Identite d'affichage d'un topic : id court (API du dashboard),
    libelle et decimales des valeurs."""
    id: str
    label: str
    decimals: int


METRICS: dict[str, Metric] = {
    "gridd.obs.environmental.temperature": Metric("temperature", "Temp\u00e9rature", 1),
    "gridd.obs.environmental.humidity": Metric("humidity", "Humidit\u00e9", 0),
    "gridd.obs.environmental.co2": Metric("co2", "CO\u2082", 0),
    "gridd.obs.acoustic.sound_level": Metric("sound_level", "Niveau sonore", 1),
    "gridd.obs.occupancy.count": Metric("occupancy", "Occupation", 0),
}

# Typographie Intl fr-CA du dashboard ; echappements explicites pour qu'un
# editeur ne les normalise pas
NBSP = "\u00a0"
NARROW_NBSP = "\u202f"
MINUS = "\u2212"

# Egalites arrondies loin de zero comme Intl (17.25 -> 17,3), pas au pair
# comme Python ; prec 400 couvre la valeur binaire exacte de tout float
_ROUNDING = Context(prec=400, rounding=ROUND_HALF_UP)
_MAX_DECIMALS = 3


def metric_for(topic: str) -> Metric:
    """Topic inconnu : id = dernier segment, libelle capitalise, 1 decimale."""
    metric = METRICS.get(topic)
    if metric:
        return metric
    last = topic.rsplit(".", 1)[-1]
    label = last.replace("_", " ")
    return Metric(last, label[:1].upper() + label[1:], 1)


def topic_label(topic: str) -> str:
    return metric_for(topic).label


def format_fixed(value: float, decimals: int) -> str:
    """Decimales fixes (largeur stable des tuiles) : 21.0 -> "21,0"."""
    rounded = Decimal(abs(value)).quantize(Decimal(1).scaleb(-decimals),
                                           context=_ROUNDING)
    integer, _, fraction = f"{rounded:,f}".partition(".")
    text = integer.replace(",", NBSP) + (f",{fraction}" if fraction else "")
    # Une valeur qui s'arrondit a zero ne garde pas son signe (pas de "-0")
    if value < 0 and rounded:
        text = MINUS + text
    return text


def format_number(value: float, max_decimals: int = 1) -> str:
    """1120 -> "1 120", 17.25 -> "17,3", -3.0 -> "-3" (vrai signe moins)."""
    text = format_fixed(value, max_decimals)
    return text.rstrip("0").rstrip(",") if "," in text else text


def format_quantity(value: float, unit: str, max_decimals: int = 1) -> str:
    """Ex. "1 000 ppm" ; sans unite, la valeur seule."""
    number = format_number(value, max_decimals)
    return f"{number}{NARROW_NBSP}{unit}" if unit else number


def format_measured(value: float, unit: str, *limits: float,
                    decimals: int = 1) -> str:
    """Au moins `decimals` decimales (3 au plus) : assez pour ne pas s'ecrire
    comme une limite qu'elle ne vaut pas : 26.04 au-dessus de 26 s'ecrit "26,04 °C", et non "26 °C"."""
    while decimals < _MAX_DECIMALS and any(
            limit != value
            and format_number(limit, decimals) == format_number(value, decimals)
            for limit in limits):
        decimals += 1
    return format_quantity(value, unit, decimals)
