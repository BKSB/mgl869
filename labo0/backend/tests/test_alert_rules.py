"""G : espace insecable des milliers (U+00A0, Intl fr-CA du dashboard) ;
F : espace fine insecable avant l'unite (U+202F)."""

import math
from dataclasses import replace

import pytest

from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    DEESCALATED,
    ESCALATED,
    RAISED,
    RESOLVED,
    WARNING,
    Alert,
    AlertEvent,
    AlertRule,
    Measurement,
    SensorState,
    evaluate,
    is_number,
    measurement_from_record,
)
from app.data_management.data_processing.formatting import (
    NARROW_NBSP as F,
    NBSP as G,
)
from tests.conftest import make_measurement

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"

# Regles livrees (config/alerts.yaml)
REGLES_CO2 = (
    AlertRule(WARNING, ABOVE, 1000, 50),
    AlertRule(CRITICAL, ABOVE, 1500, 50),
)
REGLES_TEMPERATURE = (
    AlertRule(WARNING, BELOW, 18, 0.5),
    AlertRule(WARNING, ABOVE, 26, 0.5),
    AlertRule(CRITICAL, BELOW, 16, 0.5),
    AlertRule(CRITICAL, ABOVE, 28, 0.5),
)


def measurement(valeur, ts=1000, topic=CO2, node_id="n1", unit="ppm",
                location="Zone A") -> Measurement:
    return Measurement(topic=topic, node_id=node_id, value=float(valeur),
                       unit=unit, location=location, timestamp_ms=ts)


def feed(regles, valeurs, topic=CO2, unit="ppm"):
    """Evalue les valeurs dans l'ordre (horodatages 1, 2, 3...) ; retourne
    l'etat final et les types d'evenements par mesure."""
    etat, types = SensorState(), []
    for ts, valeur in enumerate(valeurs, start=1):
        etat, evenements = evaluate(regles, measurement(valeur, ts, topic=topic,
                                                        unit=unit), etat)
        types.append([e.kind for e in evenements])
    return etat, types


class TestIsNumber:
    @pytest.mark.parametrize("valeur", [0, 3, -2.5, 1e6])
    def test_numbers(self, valeur):
        assert is_number(valeur)

    @pytest.mark.parametrize("valeur", [True, False, "12", None, [1],
                                        math.nan, math.inf, -math.inf,
                                        10**400, -10**400])
    def test_non_numbers(self, valeur):
        # 10**400 : trop grand pour un float, sans OverflowError
        assert not is_number(valeur)


class TestAlertRule:
    def test_above_at_threshold_does_not_trigger(self):
        regle = AlertRule(WARNING, ABOVE, 1000, 50)
        assert not regle.is_active(1000, was_active=False)
        assert regle.is_active(1000.1, was_active=False)

    def test_above_hysteresis(self):
        regle = AlertRule(WARNING, ABOVE, 1000, 50)
        # Active : reste active tant que v > seuil - hysteresis
        assert regle.is_active(960, was_active=True)
        assert not regle.is_active(950, was_active=True)
        # Inactive : l'hysteresis ne declenche pas
        assert not regle.is_active(960, was_active=False)

    def test_below_at_threshold_does_not_trigger(self):
        regle = AlertRule(WARNING, BELOW, 18, 0.5)
        assert not regle.is_active(18, was_active=False)
        assert regle.is_active(17.9, was_active=False)

    def test_below_hysteresis(self):
        regle = AlertRule(WARNING, BELOW, 18, 0.5)
        assert regle.is_active(18.4, was_active=True)
        assert not regle.is_active(18.5, was_active=True)
        assert not regle.is_active(18.4, was_active=False)

    def test_release(self):
        assert AlertRule(WARNING, ABOVE, 1000, 50).release == 950
        assert AlertRule(WARNING, BELOW, 18, 0.5).release == 18.5
        assert AlertRule(WARNING, ABOVE, 65).release == 65

    def test_excess(self):
        assert AlertRule(WARNING, ABOVE, 1000).excess(1120) == 120
        assert AlertRule(WARNING, BELOW, 18).excess(17) == 1
        assert AlertRule(WARNING, ABOVE, 1000).excess(980) == -20

    def test_to_dict(self):
        assert AlertRule(CRITICAL, BELOW, 16, 0.5).to_dict() == {
            "severity": "critical", "direction": "below",
            "threshold": 16.0, "hysteresis": 0.5,
        }


class TestTransitions:
    def test_raised(self):
        etat, evenements = evaluate(REGLES_CO2, measurement(1120, ts=10))

        (evenement,) = evenements
        assert evenement.kind == RAISED
        assert evenement.at_ms == 10
        alerte = evenement.alert
        assert (alerte.severity, alerte.direction, alerte.threshold) == \
            (WARNING, ABOVE, 1000)
        assert (alerte.since_ms, alerte.updated_ms, alerte.value) == \
            (10, 10, 1120)
        assert alerte.message == \
            f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}120{F}ppm)"
        assert etat.alert == alerte
        assert etat.active_rules == {0}

    def test_no_event_below_threshold(self):
        etat, evenements = evaluate(REGLES_CO2, measurement(999))
        assert evenements == []
        assert etat == SensorState()

    def test_escalated_keeps_alert_start(self):
        etat, _ = evaluate(REGLES_CO2, measurement(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, measurement(1600, ts=2), etat)

        (evenement,) = evenements
        assert evenement.kind == ESCALATED
        assert evenement.alert.severity == CRITICAL
        assert evenement.alert.threshold == 1500
        assert evenement.alert.since_ms == 1
        assert evenement.alert.updated_ms == 2
        assert etat.active_rules == {0, 1}

    def test_deescalated(self):
        etat, types = feed(REGLES_CO2, [1600, 1440])
        assert types == [[RAISED], [DEESCALATED]]
        assert etat.alert.severity == WARNING
        assert etat.alert.threshold == 1000
        assert etat.alert.since_ms == 1

    def test_resolved_carries_previous_state_and_resolving_value(self):
        avant, _ = evaluate(REGLES_CO2, measurement(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, measurement(940, ts=2), avant)

        (evenement,) = evenements
        assert evenement.kind == RESOLVED
        assert evenement.at_ms == 2
        alerte = evenement.alert
        assert (alerte.severity, alerte.threshold, alerte.since_ms) == \
            (WARNING, 1000, 1)
        assert (alerte.value, alerte.updated_ms) == (940, 2)
        # Contrat : seuls value et updated_ms changent, le message est conserve
        assert alerte == replace(avant.alert, value=940, updated_ms=2)
        assert alerte.message == \
            f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}120{F}ppm)"
        assert etat == SensorState()

    def test_resolves_directly_from_critical(self):
        _, types = feed(REGLES_CO2, [1600, 900])
        assert types == [[RAISED], [RESOLVED]]

    def test_raises_directly_as_critical(self):
        etat, types = feed(REGLES_CO2, [1600])
        assert types == [[RAISED]]
        assert etat.alert.severity == CRITICAL

    def test_same_level_updates_without_event(self):
        etat, _ = evaluate(REGLES_CO2, measurement(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, measurement(1200, ts=2), etat)

        assert evenements == []
        assert etat.alert.value == 1200
        assert etat.alert.updated_ms == 2
        assert etat.alert.since_ms == 1
        assert f"(1{G}200{F}ppm)" in etat.alert.message


class TestHysteresis:
    def test_above_stays_active_in_band(self):
        # Active tant que v > 1000 - 50 (strict) : 950 resout
        _, types = feed(REGLES_CO2, [1120, 990, 951, 950])
        assert types == [[RAISED], [], [], [RESOLVED]]

    def test_above_no_retrigger_in_band(self):
        _, types = feed(REGLES_CO2, [1120, 940, 990, 1000, 1001])
        assert types == [[RAISED], [RESOLVED], [], [], [RAISED]]

    def test_critical_stays_critical_in_its_band(self):
        _, types = feed(REGLES_CO2, [1600, 1460, 1450])
        assert types == [[RAISED], [], [DEESCALATED]]

    def test_below_symmetric(self):
        regles = (AlertRule(WARNING, BELOW, 18, 0.5),)
        _, types = feed(regles, [18, 17.9, 18.4, 18.5, 18.2, 17.99],
                        topic=TEMPERATURE, unit="\u00b0C")
        assert types == [[], [RAISED], [], [RESOLVED], [], [RAISED]]

    def test_below_message(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(17.2, topic=TEMPERATURE, unit="\u00b0C"))
        assert etat.alert.direction == BELOW
        assert etat.alert.message == \
            f"Temp\u00e9rature en dessous de 18{F}\u00b0C (17,2{F}\u00b0C)"

    def test_message_never_equals_threshold(self):
        # 26.04 depasse 26 : le message ne dit pas "au-dessus de 26 (26)"
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(26.04, topic=TEMPERATURE, unit="\u00b0C"))
        assert etat.alert.message == \
            f"Temp\u00e9rature au-dessus de 26{F}\u00b0C (26,04{F}\u00b0C)"

    def test_below_resolution_keeps_previous_message(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(17.2, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        _, (evenement,) = evaluate(
            REGLES_TEMPERATURE,
            measurement(18.6, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)
        assert evenement.kind == RESOLVED
        assert evenement.alert.value == 18.6
        assert evenement.alert.message == etat.alert.message == \
            f"Temp\u00e9rature en dessous de 18{F}\u00b0C (17,2{F}\u00b0C)"

    def test_without_hysteresis(self):
        regles = (AlertRule(WARNING, ABOVE, 65),)
        _, types = feed(regles, [66, 65.1, 65], unit="dB")
        assert types == [[RAISED], [], [RESOLVED]]


class TestMessageInBand:
    """Valeur revenue dans la bande : le message ne dit plus "au-dessus de"."""

    def test_message_in_hysteresis_band(self):
        etat, _ = feed(REGLES_CO2, [1120, 1600, 1460])
        # critical maintenue par sa bande (1460 > 1500 - 50)
        assert etat.alert.severity == CRITICAL
        assert etat.alert.message == (
            f"CO\u2082 \u00e0 1{G}460{F}ppm (seuil 1{G}500{F}ppm), niveau "
            f"critique maintenu jusqu\u2019\u00e0 1{G}450{F}ppm")

        # Sortie de la bande critical : warning, seuil 1000 franchi
        etat, _ = evaluate(REGLES_CO2, measurement(1440, ts=4), etat)
        assert etat.alert.message == \
            f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}440{F}ppm)"

        # warning maintenue par sa bande (960 > 1000 - 50)
        etat, evenements = evaluate(REGLES_CO2, measurement(960, ts=5), etat)
        assert evenements == []
        assert etat.alert.message == (
            f"CO\u2082 \u00e0 960{F}ppm (seuil 1{G}000{F}ppm), alerte "
            f"maintenue jusqu\u2019\u00e0 950{F}ppm")

    def test_value_equal_to_threshold_in_band(self):
        etat, _ = feed(REGLES_CO2, [1120, 1000])
        assert etat.alert.message.startswith(
            f"CO\u2082 \u00e0 1{G}000{F}ppm (seuil 1{G}000{F}ppm)")

    def test_below_in_band(self):
        etat, _ = feed((AlertRule(WARNING, BELOW, 18, 0.5),), [17.2, 18.2],
                       topic=TEMPERATURE, unit="\u00b0C")
        assert etat.alert.message == (
            f"Temp\u00e9rature \u00e0 18,2{F}\u00b0C (seuil 18{F}\u00b0C), "
            f"alerte maintenue jusqu\u2019\u00e0 18,5{F}\u00b0C")

    def test_resolution_after_band(self):
        avant, _ = feed(REGLES_CO2, [1120, 960])
        _, (evenement,) = evaluate(REGLES_CO2, measurement(940, ts=3), avant)
        assert evenement.kind == RESOLVED
        assert evenement.alert == replace(avant.alert, value=940, updated_ms=3)


class TestTwoSeverities:
    def test_temperature_escalates_then_recovers(self):
        etat, types = feed(REGLES_TEMPERATURE, [17, 15.9, 16.4, 16.6, 18.6],
                           topic=TEMPERATURE, unit="\u00b0C")
        assert types == [[RAISED], [ESCALATED], [], [DEESCALATED], [RESOLVED]]
        assert etat == SensorState()

    def test_highest_severity_rule_wins(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(15, topic=TEMPERATURE, unit="\u00b0C"))
        # warning < 18 et critical < 16 sont actives : critical l'emporte
        assert etat.active_rules == {0, 2}
        assert (etat.alert.severity, etat.alert.threshold) == (CRITICAL, 16)

    def test_same_severity_largest_excess_wins(self):
        regles = (AlertRule(WARNING, ABOVE, 1200), AlertRule(WARNING, ABOVE, 1000))
        etat, _ = evaluate(regles, measurement(1300))
        assert etat.alert.threshold == 1000

    @pytest.mark.parametrize("ordre", [(ABOVE, BELOW), (BELOW, ABOVE)])
    def test_exact_tie_first_rule_wins(self, ordre):
        # 1300 depasse "> 1000" et "< 1600" de 300 : la premiere l'emporte
        seuils = {ABOVE: 1000, BELOW: 1600}
        regles = tuple(AlertRule(WARNING, d, seuils[d]) for d in ordre)
        etat, _ = evaluate(regles, measurement(1300))
        assert etat.alert.direction == ordre[0]
        assert etat.active_rules == {0, 1}

    def test_direction_change_resolves_then_raises(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(27, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        etat, evenements = evaluate(
            REGLES_TEMPERATURE,
            measurement(17, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)

        assert [e.kind for e in evenements] == [RESOLVED, RAISED]
        resolu, declenche = evenements
        assert (resolu.alert.direction, resolu.alert.value) == (ABOVE, 17)
        assert resolu.alert.since_ms == 1
        assert (declenche.alert.direction, declenche.alert.since_ms) == (BELOW, 2)
        assert etat.alert == declenche.alert

    def test_direction_change_with_escalation(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           measurement(27, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        _, evenements = evaluate(
            REGLES_TEMPERATURE,
            measurement(15, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)
        assert [(e.kind, e.alert.severity) for e in evenements] == \
            [(RESOLVED, WARNING), (RAISED, CRITICAL)]


class TestSerialization:
    def test_alert_matches_contract(self):
        _, (evenement,) = evaluate(REGLES_CO2, measurement(1120, ts=10))
        assert evenement.to_dict() == {
            "kind": "raised",
            "at_ms": 10,
            "alert": {
                "id": f"{CO2}|n1",
                "topic": CO2,
                "node_id": "n1",
                "severity": "warning",
                "direction": "above",
                "threshold": 1000.0,
                "hysteresis": 50.0,
                "value": 1120.0,
                "unit": "ppm",
                "location": "Zone A",
                "since_ms": 10,
                "updated_ms": 10,
                "message": f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}120{F}ppm)",
            },
        }

    def test_hysteresis_of_responsible_rule(self):
        etat, _ = feed(REGLES_TEMPERATURE, [15], topic=TEMPERATURE,
                       unit="\u00b0C")
        assert (etat.alert.threshold, etat.alert.hysteresis) == (16, 0.5)
        etat, _ = evaluate((AlertRule(WARNING, ABOVE, 65),), measurement(70))
        assert etat.alert.hysteresis == 0.0

    def test_json_types(self):
        alerte = Alert(CO2, "n1", WARNING, ABOVE, 1000, 50, 1120, "", "", 1, 2,
                       "m")
        donnees = AlertEvent(RAISED, 2, alerte).to_dict()["alert"]
        assert isinstance(donnees["threshold"], float)
        assert isinstance(donnees["hysteresis"], float)
        assert isinstance(donnees["value"], float)
        assert donnees["unit"] == "" and donnees["location"] == ""


class TestMeasurementFromRecord:
    def test_complete_measurement(self):
        record = make_measurement(1120, timestamp_ms=42, node_id="n7", topic=CO2)
        assert measurement_from_record(CO2, record) == Measurement(
            topic=CO2, node_id="n7", value=1120.0, unit="ppm",
            location="Zone A", timestamp_ms=42)

    def test_location_falls_back_to_space(self):
        record = make_measurement(zone=None, space="Salle 101")
        assert measurement_from_record("t", record).location == "Salle 101"

    def test_location_skips_unlabeled_zone(self):
        record = make_measurement(zone="", space="Salle 101")
        assert measurement_from_record("t", record).location == "Salle 101"

    def test_without_location(self):
        record = make_measurement(zone=None, space=None)
        assert measurement_from_record("t", record).location == ""
        record["value"]["metadata"] = "pas un dictionnaire"
        assert measurement_from_record("t", record).location == ""
        del record["value"]["metadata"]
        assert measurement_from_record("t", record).location == ""

    def test_missing_or_invalid_unit(self):
        record = make_measurement()
        del record["value"]["unit"]
        assert measurement_from_record("t", record).unit == ""
        record["value"]["unit"] = 3
        assert measurement_from_record("t", record).unit == ""

    def test_sensor_falls_back_to_kafka_key(self):
        record = make_measurement(node_id=None)
        record["key"] = "cle-1"
        assert measurement_from_record("t", record).node_id == "cle-1"

    def test_integer_value_converted_to_float(self):
        mesure_ = measurement_from_record("t", make_measurement(1000))
        assert mesure_.value == 1000.0 and isinstance(mesure_.value, float)

    @pytest.mark.parametrize("valeur", ["21.5", None, True, math.nan])
    def test_non_numeric_value(self, valeur):
        assert measurement_from_record("t", make_measurement(valeur)) is None

    @pytest.mark.parametrize("payload", ["texte brut", None, 12])
    def test_non_json_payload(self, payload):
        record = make_measurement()
        record["value"] = payload
        assert measurement_from_record("t", record) is None

    @pytest.mark.parametrize("horodatage", [None, "1000", 1000.5, True])
    def test_invalid_timestamp(self, horodatage):
        record = make_measurement(timestamp_ms=horodatage)
        assert measurement_from_record("t", record) is None
