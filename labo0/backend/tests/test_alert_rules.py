"""Tests de l'evaluation pure des regles d'alerte : activation avec
hysteresis, niveau et regle responsable, transitions, messages (dont la
bande d'hysteresis) et extraction de la mesure d'un record.

Typographie : G est l'espace insecable des milliers (U+00A0, comme Intl
fr-CA cote dashboard), F l'espace fine insecable avant l'unite (U+202F)."""

import math
from dataclasses import replace

import pytest

from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    DEESCALATED,
    ESCALATED,
    MINUS,
    NARROW_NBSP as F,
    NBSP as G,
    RAISED,
    RESOLVED,
    WARNING,
    Alert,
    AlertEvent,
    AlertRule,
    Measurement,
    SensorState,
    alert_id,
    evaluate,
    format_measured,
    format_number,
    format_quantity,
    is_number,
    measurement_from_record,
    topic_label,
)
from tests.conftest import make_mesure

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"

# Regles CO2 livrees : warning > 1000, critical > 1500, hysteresis 50
REGLES_CO2 = (
    AlertRule(WARNING, ABOVE, 1000, 50),
    AlertRule(CRITICAL, ABOVE, 1500, 50),
)
# Regles temperature livrees (hysteresis 0.5)
REGLES_TEMPERATURE = (
    AlertRule(WARNING, BELOW, 18, 0.5),
    AlertRule(WARNING, ABOVE, 26, 0.5),
    AlertRule(CRITICAL, BELOW, 16, 0.5),
    AlertRule(CRITICAL, ABOVE, 28, 0.5),
)


def mesure(valeur, ts=1000, topic=CO2, node_id="n1", unit="ppm",
           location="Zone A") -> Measurement:
    return Measurement(topic=topic, node_id=node_id, value=float(valeur),
                       unit=unit, location=location, timestamp_ms=ts)


def suite(regles, valeurs, topic=CO2, unit="ppm"):
    """Evalue une suite de valeurs (horodatages 1, 2, 3...) ; retourne
    l'etat final et la liste, par mesure, des types d'evenements."""
    etat, types = SensorState(), []
    for ts, valeur in enumerate(valeurs, start=1):
        etat, evenements = evaluate(regles, mesure(valeur, ts, topic=topic,
                                                   unit=unit), etat)
        types.append([e.kind for e in evenements])
    return etat, types


class TestFormatage:
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
        # Egalites exactes en binaire : arrondies en s'eloignant de zero,
        # comme Intl.NumberFormat (le format de Python donnerait 17,2)
        (17.25, "17,3"),
        (26.25, "26,3"),
        (65.25, "65,3"),
        (-17.25, f"{MINUS}17,3"),
        # 0.15 vaut 0.1499... en binaire : pas une egalite (Intl aussi : 0,1)
        (0.15, "0,1"),
    ])
    def test_egalites_arrondies_comme_le_dashboard(self, valeur, attendu):
        assert format_number(valeur) == attendu

    def test_nombre_de_decimales(self):
        assert format_number(26.04, 2) == "26,04"
        assert format_number(26.5, 0) == "27"
        assert format_number(1120.0, 3) == f"1{G}120"

    def test_tres_grande_valeur_sans_erreur(self):
        assert format_number(3.4028235e38).startswith(f"340{G}282{G}3")

    def test_format_quantity_avec_et_sans_unite(self):
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
    def test_valeur_mesuree_distincte_des_limites(self, valeur, limites,
                                                  attendu):
        assert format_measured(valeur, "ppm", *limites) == attendu

    def test_espaces_comme_le_dashboard(self):
        # Milliers : U+00A0 (Intl fr-CA de lib/format.ts) ; avant l'unite :
        # U+202F (fmtValue). Les messages s'affichent a cote des tuiles.
        assert G == "\u00a0" and F == "\u202f"
        assert format_quantity(1535, "ppm") == "1\u00a0535\u202fppm"

    def test_libelles_des_topics(self):
        assert topic_label(CO2) == "CO\u2082"
        assert topic_label(TEMPERATURE) == "Temp\u00e9rature"
        assert topic_label("gridd.obs.acoustic.sound_level") == "Niveau sonore"

    def test_libelle_de_repli_dernier_segment(self):
        assert topic_label("gridd.obs.wind.wind_speed") == "Wind speed"
        assert topic_label("simple") == "Simple"

    def test_alert_id(self):
        assert alert_id(CO2, "n1") == f"{CO2}|n1"


class TestIsNumber:
    @pytest.mark.parametrize("valeur", [0, 3, -2.5, 1e6])
    def test_nombres(self, valeur):
        assert is_number(valeur)

    @pytest.mark.parametrize("valeur", [True, False, "12", None, [1],
                                        math.nan, math.inf, -math.inf,
                                        10**400, -10**400])
    def test_non_nombres(self, valeur):
        # Un entier trop grand pour un float n'est pas un nombre (sans
        # OverflowError)
        assert not is_number(valeur)


class TestAlertRule:
    def test_above_seuil_exact_non_declenchant(self):
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

    def test_below_seuil_exact_non_declenchant(self):
        regle = AlertRule(WARNING, BELOW, 18, 0.5)
        assert not regle.is_active(18, was_active=False)
        assert regle.is_active(17.9, was_active=False)

    def test_below_hysteresis(self):
        regle = AlertRule(WARNING, BELOW, 18, 0.5)
        assert regle.is_active(18.4, was_active=True)
        assert not regle.is_active(18.5, was_active=True)
        assert not regle.is_active(18.4, was_active=False)

    def test_limite_de_la_bande(self):
        assert AlertRule(WARNING, ABOVE, 1000, 50).release == 950
        assert AlertRule(WARNING, BELOW, 18, 0.5).release == 18.5
        assert AlertRule(WARNING, ABOVE, 65).release == 65

    def test_depassement(self):
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
        etat, evenements = evaluate(REGLES_CO2, mesure(1120, ts=10))

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

    def test_aucun_evenement_sous_le_seuil(self):
        etat, evenements = evaluate(REGLES_CO2, mesure(999))
        assert evenements == []
        assert etat == SensorState()

    def test_escalated_garde_le_debut_de_l_alerte(self):
        etat, _ = evaluate(REGLES_CO2, mesure(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, mesure(1600, ts=2), etat)

        (evenement,) = evenements
        assert evenement.kind == ESCALATED
        assert evenement.alert.severity == CRITICAL
        assert evenement.alert.threshold == 1500
        assert evenement.alert.since_ms == 1
        assert evenement.alert.updated_ms == 2
        assert etat.active_rules == {0, 1}

    def test_deescalated(self):
        etat, types = suite(REGLES_CO2, [1600, 1440])
        assert types == [[RAISED], [DEESCALATED]]
        assert etat.alert.severity == WARNING
        assert etat.alert.threshold == 1000
        assert etat.alert.since_ms == 1

    def test_resolved_porte_l_etat_precedent_et_la_mesure_qui_resout(self):
        avant, _ = evaluate(REGLES_CO2, mesure(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, mesure(940, ts=2), avant)

        (evenement,) = evenements
        assert evenement.kind == RESOLVED
        assert evenement.at_ms == 2
        alerte = evenement.alert
        assert (alerte.severity, alerte.threshold, alerte.since_ms) == \
            (WARNING, 1000, 1)
        assert (alerte.value, alerte.updated_ms) == (940, 2)
        # Contrat : seules la valeur et l'horodatage changent, le message
        # reste celui de l'etat juste avant la resolution
        assert alerte == replace(avant.alert, value=940, updated_ms=2)
        assert alerte.message == \
            f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}120{F}ppm)"
        assert etat == SensorState()

    def test_resolution_directe_depuis_critical(self):
        _, types = suite(REGLES_CO2, [1600, 900])
        assert types == [[RAISED], [RESOLVED]]

    def test_declenchement_direct_en_critical(self):
        etat, types = suite(REGLES_CO2, [1600])
        assert types == [[RAISED]]
        assert etat.alert.severity == CRITICAL

    def test_meme_niveau_mise_a_jour_sans_evenement(self):
        etat, _ = evaluate(REGLES_CO2, mesure(1120, ts=1))
        etat, evenements = evaluate(REGLES_CO2, mesure(1200, ts=2), etat)

        assert evenements == []
        assert etat.alert.value == 1200
        assert etat.alert.updated_ms == 2
        assert etat.alert.since_ms == 1
        assert f"(1{G}200{F}ppm)" in etat.alert.message


class TestHysteresis:
    def test_above_reste_active_dans_la_bande(self):
        # 1120 declenche ; 990 et 951 restent dans la bande (> 950) ;
        # 950 resout (pas strictement au-dessus de 1000 - 50)
        _, types = suite(REGLES_CO2, [1120, 990, 951, 950])
        assert types == [[RAISED], [], [], [RESOLVED]]

    def test_above_pas_de_redeclenchement_dans_la_bande(self):
        # Apres resolution, revenir dans la bande ne redeclenche pas
        _, types = suite(REGLES_CO2, [1120, 940, 990, 1000, 1001])
        assert types == [[RAISED], [RESOLVED], [], [], [RAISED]]

    def test_critical_reste_critical_dans_sa_bande(self):
        _, types = suite(REGLES_CO2, [1600, 1460, 1450])
        assert types == [[RAISED], [], [DEESCALATED]]

    def test_below_symetrique(self):
        regles = (AlertRule(WARNING, BELOW, 18, 0.5),)
        _, types = suite(regles, [18, 17.9, 18.4, 18.5, 18.2, 17.99],
                         topic=TEMPERATURE, unit="\u00b0C")
        assert types == [[], [RAISED], [], [RESOLVED], [], [RAISED]]

    def test_below_message(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(17.2, topic=TEMPERATURE, unit="\u00b0C"))
        assert etat.alert.direction == BELOW
        assert etat.alert.message == \
            f"Temp\u00e9rature en dessous de 18{F}\u00b0C (17,2{F}\u00b0C)"

    def test_message_jamais_egal_au_seuil(self):
        # 26.04 depasse 26 : le message ne dit pas "au-dessus de 26 (26)"
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(26.04, topic=TEMPERATURE, unit="\u00b0C"))
        assert etat.alert.message == \
            f"Temp\u00e9rature au-dessus de 26{F}\u00b0C (26,04{F}\u00b0C)"

    def test_below_resolution_garde_le_message_precedent(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(17.2, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        _, (evenement,) = evaluate(
            REGLES_TEMPERATURE,
            mesure(18.6, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)
        assert evenement.kind == RESOLVED
        assert evenement.alert.value == 18.6
        assert evenement.alert.message == etat.alert.message == \
            f"Temp\u00e9rature en dessous de 18{F}\u00b0C (17,2{F}\u00b0C)"

    def test_sans_hysteresis(self):
        regles = (AlertRule(WARNING, ABOVE, 65),)
        _, types = suite(regles, [66, 65.1, 65], unit="dB")
        assert types == [[RAISED], [], [RESOLVED]]


class TestMessageDansLaBande:
    """Regle maintenue par l'hysteresis alors que la valeur est revenue en
    deca du seuil : le message ne dit plus "au-dessus de <seuil>"."""

    def test_message_dans_la_bande_d_hysteresis(self):
        etat, _ = suite(REGLES_CO2, [1120, 1600, 1460])
        # critical maintenue par sa bande (1460 > 1500 - 50)
        assert etat.alert.severity == CRITICAL
        assert etat.alert.message == (
            f"CO\u2082 \u00e0 1{G}460{F}ppm (seuil 1{G}500{F}ppm), niveau "
            f"critique maintenu jusqu\u2019\u00e0 1{G}450{F}ppm")

        # Sortie de la bande critical : warning, seuil 1000 franchi
        etat, _ = evaluate(REGLES_CO2, mesure(1440, ts=4), etat)
        assert etat.alert.message == \
            f"CO\u2082 au-dessus de 1{G}000{F}ppm (1{G}440{F}ppm)"

        # warning maintenue par sa bande (960 > 1000 - 50)
        etat, evenements = evaluate(REGLES_CO2, mesure(960, ts=5), etat)
        assert evenements == []
        assert etat.alert.message == (
            f"CO\u2082 \u00e0 960{F}ppm (seuil 1{G}000{F}ppm), alerte "
            f"maintenue jusqu\u2019\u00e0 950{F}ppm")

    def test_valeur_egale_au_seuil_dans_la_bande(self):
        etat, _ = suite(REGLES_CO2, [1120, 1000])
        assert etat.alert.message.startswith(
            f"CO\u2082 \u00e0 1{G}000{F}ppm (seuil 1{G}000{F}ppm)")

    def test_below_dans_la_bande(self):
        etat, _ = suite((AlertRule(WARNING, BELOW, 18, 0.5),), [17.2, 18.2],
                        topic=TEMPERATURE, unit="\u00b0C")
        assert etat.alert.message == (
            f"Temp\u00e9rature \u00e0 18,2{F}\u00b0C (seuil 18{F}\u00b0C), "
            f"alerte maintenue jusqu\u2019\u00e0 18,5{F}\u00b0C")

    def test_resolution_apres_la_bande(self):
        avant, _ = suite(REGLES_CO2, [1120, 960])
        _, (evenement,) = evaluate(REGLES_CO2, mesure(940, ts=3), avant)
        assert evenement.kind == RESOLVED
        assert evenement.alert == replace(avant.alert, value=940, updated_ms=3)


class TestDeuxSeverites:
    def test_temperature_escalade_et_retour(self):
        etat, types = suite(REGLES_TEMPERATURE, [17, 15.9, 16.4, 16.6, 18.6],
                            topic=TEMPERATURE, unit="\u00b0C")
        assert types == [[RAISED], [ESCALATED], [], [DEESCALATED], [RESOLVED]]
        assert etat == SensorState()

    def test_regle_responsable_de_plus_haute_severite(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(15, topic=TEMPERATURE, unit="\u00b0C"))
        # warning < 18 et critical < 16 sont actives : critical l'emporte
        assert etat.active_rules == {0, 2}
        assert (etat.alert.severity, etat.alert.threshold) == (CRITICAL, 16)

    def test_a_severite_egale_le_plus_grand_depassement(self):
        regles = (AlertRule(WARNING, ABOVE, 1200), AlertRule(WARNING, ABOVE, 1000))
        etat, _ = evaluate(regles, mesure(1300))
        assert etat.alert.threshold == 1000

    @pytest.mark.parametrize("ordre", [(ABOVE, BELOW), (BELOW, ABOVE)])
    def test_a_egalite_parfaite_la_premiere_regle(self, ordre):
        # 1300 depasse "> 1000" et "< 1600" de 300 : la premiere l'emporte
        seuils = {ABOVE: 1000, BELOW: 1600}
        regles = tuple(AlertRule(WARNING, d, seuils[d]) for d in ordre)
        etat, _ = evaluate(regles, mesure(1300))
        assert etat.alert.direction == ordre[0]
        assert etat.active_rules == {0, 1}

    def test_changement_de_direction_resout_puis_declenche(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(27, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        etat, evenements = evaluate(
            REGLES_TEMPERATURE,
            mesure(17, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)

        assert [e.kind for e in evenements] == [RESOLVED, RAISED]
        resolu, declenche = evenements
        assert (resolu.alert.direction, resolu.alert.value) == (ABOVE, 17)
        assert resolu.alert.since_ms == 1
        assert (declenche.alert.direction, declenche.alert.since_ms) == (BELOW, 2)
        assert etat.alert == declenche.alert

    def test_changement_de_direction_avec_escalade(self):
        etat, _ = evaluate(REGLES_TEMPERATURE,
                           mesure(27, ts=1, topic=TEMPERATURE, unit="\u00b0C"))
        _, evenements = evaluate(
            REGLES_TEMPERATURE,
            mesure(15, ts=2, topic=TEMPERATURE, unit="\u00b0C"), etat)
        assert [(e.kind, e.alert.severity) for e in evenements] == \
            [(RESOLVED, WARNING), (RAISED, CRITICAL)]


class TestSerialisation:
    def test_alerte_conforme_au_contrat(self):
        _, (evenement,) = evaluate(REGLES_CO2, mesure(1120, ts=10))
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

    def test_hysteresis_de_la_regle_responsable(self):
        etat, _ = suite(REGLES_TEMPERATURE, [15], topic=TEMPERATURE,
                        unit="\u00b0C")
        assert (etat.alert.threshold, etat.alert.hysteresis) == (16, 0.5)
        etat, _ = evaluate((AlertRule(WARNING, ABOVE, 65),), mesure(70))
        assert etat.alert.hysteresis == 0.0

    def test_types_json(self):
        alerte = Alert(CO2, "n1", WARNING, ABOVE, 1000, 50, 1120, "", "", 1, 2,
                       "m")
        donnees = AlertEvent(RAISED, 2, alerte).to_dict()["alert"]
        assert isinstance(donnees["threshold"], float)
        assert isinstance(donnees["hysteresis"], float)
        assert isinstance(donnees["value"], float)
        assert donnees["unit"] == "" and donnees["location"] == ""


class TestMeasurementFromRecord:
    def test_mesure_complete(self):
        record = make_mesure(1120, timestamp_ms=42, node_id="n7", topic=CO2)
        assert measurement_from_record(CO2, record) == Measurement(
            topic=CO2, node_id="n7", value=1120.0, unit="ppm",
            location="Zone A", timestamp_ms=42)

    def test_emplacement_repli_sur_l_espace(self):
        record = make_mesure(zone=None, space="Salle 101")
        assert measurement_from_record("t", record).location == "Salle 101"

    def test_emplacement_zone_sans_libelle(self):
        record = make_mesure(zone="", space="Salle 101")
        assert measurement_from_record("t", record).location == "Salle 101"

    def test_sans_emplacement(self):
        record = make_mesure(zone=None, space=None)
        assert measurement_from_record("t", record).location == ""
        record["value"]["metadata"] = "pas un dictionnaire"
        assert measurement_from_record("t", record).location == ""
        del record["value"]["metadata"]
        assert measurement_from_record("t", record).location == ""

    def test_unite_absente_ou_invalide(self):
        record = make_mesure()
        del record["value"]["unit"]
        assert measurement_from_record("t", record).unit == ""
        record["value"]["unit"] = 3
        assert measurement_from_record("t", record).unit == ""

    def test_capteur_identifie_par_la_cle_kafka_a_defaut(self):
        record = make_mesure(node_id=None)
        record["key"] = "cle-1"
        assert measurement_from_record("t", record).node_id == "cle-1"

    def test_valeur_entiere_convertie_en_float(self):
        mesure_ = measurement_from_record("t", make_mesure(1000))
        assert mesure_.value == 1000.0 and isinstance(mesure_.value, float)

    @pytest.mark.parametrize("valeur", ["21.5", None, True, math.nan])
    def test_valeur_non_numerique(self, valeur):
        assert measurement_from_record("t", make_mesure(valeur)) is None

    @pytest.mark.parametrize("payload", ["texte brut", None, 12])
    def test_payload_non_json(self, payload):
        record = make_mesure()
        record["value"] = payload
        assert measurement_from_record("t", record) is None

    @pytest.mark.parametrize("horodatage", [None, "1000", 1000.5, True])
    def test_horodatage_invalide(self, horodatage):
        record = make_mesure(timestamp_ms=horodatage)
        assert measurement_from_record("t", record) is None
