"""Formatage des messages d'alerte, aligne sur frontend/src/lib/format.ts."""

from decimal import ROUND_HALF_UP, Context, Decimal

# Memes libelles que le dashboard
TOPIC_LABELS = {
    "gridd.obs.environmental.temperature": "Temp\u00e9rature",
    "gridd.obs.environmental.humidity": "Humidit\u00e9",
    "gridd.obs.environmental.co2": "CO\u2082",
    "gridd.obs.acoustic.sound_level": "Niveau sonore",
    "gridd.obs.occupancy.count": "Occupation",
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


def topic_label(topic: str) -> str:
    label = TOPIC_LABELS.get(topic)
    if label:
        return label
    last = topic.rsplit(".", 1)[-1].replace("_", " ")
    return last[:1].upper() + last[1:]


def format_number(value: float, max_decimals: int = 1) -> str:
    """1120 -> "1 120", 17.25 -> "17,3", -3.0 -> "-3" (vrai signe moins)."""
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
    """Ex. "1 000 ppm" ; sans unite, la valeur seule."""
    number = format_number(value, max_decimals)
    return f"{number}{NARROW_NBSP}{unit}" if unit else number


def format_measured(value: float, unit: str, *limits: float) -> str:
    """Assez de decimales pour ne pas s'ecrire comme une limite qu'elle ne
    vaut pas : 26.04 au-dessus de 26 s'ecrit "26,04 °C", et non "26 °C"."""
    decimals = 1
    while decimals < _MAX_DECIMALS and any(
            limit != value
            and format_number(limit, decimals) == format_number(value, decimals)
            for limit in limits):
        decimals += 1
    return format_quantity(value, unit, decimals)
