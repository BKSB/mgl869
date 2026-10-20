"""Meme rendu que le dashboard. G : espace insecable des milliers (U+00A0,
Intl fr-CA) ; F : espace fine insecable avant l'unite (U+202F)."""

import pytest

from app.data_management.data_processing.formatting import (
    MINUS,
    NARROW_NBSP as F,
    NBSP as G,
    format_fixed,
    format_measured,
    format_number,
    format_quantity,
    metric_for,
    topic_label,
)

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"


class TestFormatting:
    @pytest.mark.parametrize("valeur,attendu", [
        (0, "0"),
        (26, "26"),
        (26.0, "26"),
        (17.24, "17,2"),
        (0.5, "0,5"),
        (999, "999"),
        (1000, f"1{G}000"),
        (1120.0, f"1{G}120"),
        (999.96, f"1{G}000"),
        (1234567.89, f"1{G}234{G}567,9"),
        (-3.0, f"{MINUS}3"),
        (-2.54, f"{MINUS}2,5"),
        (-0.04, "0"),
    ])
    def test_format_number(self, valeur, attendu):
        assert format_number(valeur) == attendu

    @pytest.mark.parametrize("valeur,attendu", [
        # Egalite binaire exacte : loin de zero comme Intl (Python : 17,2)
        (17.25, "17,3"),
        (26.25, "26,3"),
        (65.25, "65,3"),
        (-17.25, f"{MINUS}17,3"),
        # 0.15 vaut 0.1499... en binaire : pas une egalite (Intl aussi : 0,1)
        (0.15, "0,1"),
    ])
    def test_ties_rounded_like_dashboard(self, valeur, attendu):
        assert format_number(valeur) == attendu

    def test_decimal_places(self):
        assert format_number(26.04, 2) == "26,04"
        assert format_number(26.5, 0) == "27"
        assert format_number(1120.0, 3) == f"1{G}120"

    def test_huge_value_without_error(self):
        assert format_number(3.4028235e38).startswith(f"340{G}282{G}3")

    def test_format_quantity_with_and_without_unit(self):
        assert format_quantity(1000, "ppm") == f"1{G}000{F}ppm"
        assert format_quantity(17.5, "") == "17,5"
        assert format_quantity(26.04, "°C", 2) == f"26,04{F}°C"

    @pytest.mark.parametrize("valeur,limites,attendu", [
        (1120, (1000,), f"1{G}120{F}ppm"),
        # Arrondie a 1 decimale, la valeur s'ecrirait comme le seuil
        (1000.04, (1000,), f"1{G}000,04{F}ppm"),
        (1000.0004, (1000,), f"1{G}000{F}ppm"),  # 3 decimales au plus
        (1000.0006, (1000,), f"1{G}000,001{F}ppm"),
        # Egale a la limite : rien a distinguer
        (1000, (1000,), f"1{G}000{F}ppm"),
        # Bande d'hysteresis : ni le seuil ni la fin de bande
        (950.02, (1000, 950), f"950,02{F}ppm"),
    ])
    def test_measured_value_distinct_from_limits(self, valeur, limites,
                                                 attendu):
        assert format_measured(valeur, "ppm", *limites) == attendu

    def test_spaces_like_dashboard(self):
        # Comme lib/format.ts : les messages s'affichent a cote des tuiles
        assert G == "\u00a0" and F == "\u202f"
        assert format_quantity(1535, "ppm") == "1\u00a0535\u202fppm"

    def test_topic_labels(self):
        assert topic_label(CO2) == "CO\u2082"
        assert topic_label(TEMPERATURE) == "Temp\u00e9rature"
        assert topic_label("gridd.obs.acoustic.sound_level") == "Niveau sonore"

    def test_fallback_label_is_last_segment(self):
        assert topic_label("gridd.obs.wind.wind_speed") == "Wind speed"
        assert topic_label("simple") == "Simple"


class TestFixedDecimals:
    @pytest.mark.parametrize("valeur,decimales,attendu", [
        (21.0, 1, "21,0"),
        (21.04, 1, "21,0"),
        (21.05, 1, "21,1"),
        (1240, 0, f"1{G}240"),
        (1240.6, 0, f"1{G}241"),
        (0, 2, "0,00"),
        (-0.04, 1, "0,0"),
        (-2.5, 1, f"{MINUS}2,5"),
    ])
    def test_format_fixed(self, valeur, decimales, attendu):
        assert format_fixed(valeur, decimales) == attendu

    def test_measured_starts_at_metric_decimals(self):
        # CO2 sans decimale : une de plus seulement pour se distinguer du seuil
        assert format_measured(1240, "ppm", 1000, decimals=0) == f"1{G}240{F}ppm"
        assert format_measured(1000.4, "ppm", 1000, decimals=0) == \
            f"1{G}000,4{F}ppm"


class TestMetrics:
    def test_known_topics(self):
        temperature = metric_for(TEMPERATURE)
        assert (temperature.id, temperature.decimals) == ("temperature", 1)
        assert temperature.label == topic_label(TEMPERATURE)
        assert (metric_for(CO2).id, metric_for(CO2).decimals) == ("co2", 0)
        assert metric_for("gridd.obs.acoustic.sound_level").id == "sound_level"
        assert metric_for("gridd.obs.occupancy.count").decimals == 0

    def test_unknown_topic(self):
        metric = metric_for("gridd.obs.wind.wind_speed")
        assert (metric.id, metric.label, metric.decimals) == \
            ("wind_speed", "Wind speed", 1)
