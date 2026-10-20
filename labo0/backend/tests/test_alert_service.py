import logging

import pytest

from app.config import AlertsConfig
from app.data_management.data_processing.alert_rules import (
    ABOVE,
    BELOW,
    CRITICAL,
    WARNING,
    AlertRule,
)
from app.data_management.record_bus import RecordBus
from app.services.alert_service import AlertService
from tests.conftest import drain, make_measurement

CO2 = "gridd.obs.environmental.co2"
TEMPERATURE = "gridd.obs.environmental.temperature"


def alerts_config() -> AlertsConfig:
    return AlertsConfig(enabled=True, source="alerts.yaml", rules={
        CO2: [AlertRule(WARNING, ABOVE, 1000, 50),
              AlertRule(CRITICAL, ABOVE, 1500, 50)],
        TEMPERATURE: [AlertRule(WARNING, BELOW, 18, 0.5)],
    })


@pytest.fixture
def service():
    return AlertService(alerts_config())


class Emitter:
    """Publie des mesures CO2 sur le service, offsets croissants par defaut."""

    def __init__(self, service: AlertService):
        self.service = service
        self.offset = 0

    async def __call__(self, valeur, ts, node_id="n1", topic=CO2, replay=False,
                       offset=None, partition=0, **kwargs):
        if offset is None:
            self.offset += 1
            offset = self.offset
        record = make_measurement(valeur, timestamp_ms=ts, offset=offset,
                                  node_id=node_id, partition=partition, topic=topic,
                                  **kwargs)
        await self.service.on_record(topic, record, replay=replay)
        return record


@pytest.fixture
def emit(service):
    return Emitter(service)


def types(service: AlertService) -> list[str]:
    """Types des evenements recents, du plus ancien au plus recent."""
    return [e["kind"] for e in reversed(service.recent())]


class TestConfiguration:
    def test_rules_exposed(self, service):
        assert service.enabled
        assert service.rules() == {
            CO2: [
                {"severity": "warning", "direction": "above",
                 "threshold": 1000.0, "hysteresis": 50.0},
                {"severity": "critical", "direction": "above",
                 "threshold": 1500.0, "hysteresis": 50.0},
            ],
            TEMPERATURE: [
                {"severity": "warning", "direction": "below",
                 "threshold": 18.0, "hysteresis": 0.5},
            ],
        }

    def test_topic_without_rules_omitted(self):
        service = AlertService(AlertsConfig(enabled=True, rules={CO2: []}))
        assert service.rules() == {}

    def test_logs_rules_at_startup(self, caplog):
        with caplog.at_level(logging.INFO):
            AlertService(alerts_config())
        assert "3 regle(s) sur 2 topic(s)" in caplog.text

    async def test_disabled(self, caplog):
        config = alerts_config()
        config.enabled = False
        with caplog.at_level(logging.INFO):
            service = AlertService(config)

        await service.on_record(CO2, make_measurement(2000), replay=False)

        assert not service.enabled
        assert service.rules() == {}
        assert service.active() == []
        assert service.recent() == []
        assert "regle(s)" not in caplog.text
        assert drain(service.subscribe()) == [{"type": "snapshot", "active": []}]


class TestOnRecord:
    async def test_raises_alert(self, service, emit):
        await emit(1120, ts=100)

        (alerte,) = service.active()
        assert alerte["id"] == f"{CO2}|n1"
        assert alerte["severity"] == "warning"
        assert alerte["location"] == "Zone A"
        assert alerte["since_ms"] == 100
        assert types(service) == ["raised"]

    async def test_replay_rebuilds_state_without_event(self, service,
                                                       emit):
        queue = service.subscribe()
        await emit(1120, ts=100, replay=True)

        # Active, sans evenement historise ni diffuse : abonnes resynchronises
        (alerte,) = service.active()
        assert (alerte["severity"], alerte["since_ms"]) == ("warning", 100)
        assert service.recent() == []
        initial, resync = drain(queue)
        assert initial == {"type": "snapshot", "active": []}
        assert resync == {"type": "snapshot", "active": [alerte]}

    async def test_replay_without_level_change_sends_nothing(
            self, service, emit):
        queue = service.subscribe()
        await emit(1120, ts=100, replay=True)
        await emit(1200, ts=200, replay=True)

        assert [m["type"] for m in drain(queue)] == ["snapshot", "snapshot"]
        assert service.active()[0]["value"] == 1200

    async def test_replayed_then_consumed_record_evaluated_once(self, service,
                                                              emit):
        record = await emit(1120, ts=100, replay=True)
        # Relu apres le prechauffage (reprise sur les offsets commites)
        await service.on_record(CO2, record, replay=False)

        assert service.recent() == []
        assert len(service.active()) == 1

    async def test_restart_alert_held_by_hysteresis(
            self, service, emit):
        """Rejeu 1120 puis 980 (> 950) : a 985, meme alerte, sans evenement."""
        await emit(1120, ts=100, replay=True)
        await emit(980, ts=200, replay=True)
        await emit(985, ts=300)

        (alerte,) = service.active()
        assert (alerte["value"], alerte["since_ms"]) == (985, 100)
        assert service.recent() == []

    async def test_live_after_replay(self, service, emit):
        await emit(1120, ts=100, replay=True)
        await emit(1600, ts=200)

        assert types(service) == ["escalated"]
        assert service.recent()[0]["alert"]["since_ms"] == 100

    async def test_duplicate_ignored(self, service, emit):
        await emit(1120, ts=100, offset=7)
        # Relecture Kafka (meme offset) : ignoree meme si le contenu differe
        await emit(900, ts=100, offset=7)

        assert types(service) == ["raised"]
        assert service.active()[0]["value"] == 1120

    async def test_stale_offset_ignored(self, service, emit):
        await emit(1120, ts=100, offset=1)
        await emit(1130, ts=200, offset=2)
        await emit(900, ts=300, offset=1)

        assert types(service) == ["raised"]
        assert service.active()[0]["value"] == 1130

    async def test_offsets_per_topic_and_partition(self, service, emit):
        await emit(1120, ts=100, offset=7)
        await emit(900, ts=100, offset=8)
        # Meme offset, autre partition ou autre topic : records distincts
        await emit(1120, ts=100, offset=7, partition=1)
        await emit(17, ts=100, offset=7, topic=TEMPERATURE, unit="C")

        assert types(service) == ["raised", "resolved", "raised", "raised"]

    async def test_same_partition_offset_order_prevails(self, service,
                                                              emit):
        await emit(1120, ts=200)
        # Horloge corrigee : horodatage qui recule, mais offset plus recent
        await emit(900, ts=100)

        assert types(service) == ["raised", "resolved"]

    async def test_future_timestamp_does_not_freeze_sensor(self, service,
                                                          emit):
        demain = 100 + 24 * 3600 * 1000
        await emit(1600, ts=demain)
        await emit(400, ts=100)

        assert types(service) == ["raised", "resolved"]
        assert service.active() == []

    async def test_other_partition_older_measurement_ignored(self, service,
                                                          emit):
        await emit(1120, ts=200, partition=0)
        # Capteur sur plusieurs partitions : l'horodatage departage
        await emit(900, ts=100, partition=1)
        assert types(service) == ["raised"]
        assert service.active()[0]["updated_ms"] == 200

        # Plus recente, elle est evaluee
        await emit(900, ts=300, partition=1)
        assert types(service) == ["raised", "resolved"]

    @pytest.mark.parametrize("valeur", ["1200", None, True])
    async def test_non_numeric_value_ignored(self, service, emit, valeur):
        await emit(valeur, ts=100)
        assert service.active() == []
        assert service.recent() == []

    async def test_non_json_payload_ignored(self, service):
        record = make_measurement(1200, topic=CO2)
        record["value"] = "texte brut"
        await service.on_record(CO2, record, replay=False)
        assert service.recent() == []

    async def test_topic_without_rules_ignored(self, service, emit):
        await emit(5000, ts=100, topic="gridd.obs.occupancy.count")
        assert service.active() == []
        assert service.recent() == []

    async def test_independent_sensors(self, service, emit):
        await emit(1120, ts=100, node_id="n1")
        await emit(900, ts=50, node_id="n2")
        await emit(1600, ts=60, node_id="n2")

        assert {a["node_id"]: a["severity"] for a in service.active()} == \
            {"n1": "warning", "n2": "critical"}

    async def test_same_sensor_on_two_topics(self, service, emit):
        await emit(1120, ts=100, node_id="n1")
        await emit(17, ts=100, node_id="n1", topic=TEMPERATURE, unit="C")

        assert sorted(a["id"] for a in service.active()) == \
            [f"{CO2}|n1", f"{TEMPERATURE}|n1"]

    async def test_update_without_event(self, service, emit):
        await emit(1120, ts=100)
        await emit(1250, ts=200, zone="Zone B")

        (alerte,) = service.active()
        assert (alerte["value"], alerte["updated_ms"], alerte["since_ms"]) == \
            (1250, 200, 100)
        assert alerte["location"] == "Zone B"
        assert types(service) == ["raised"]

    async def test_full_cycle(self, service, emit):
        for ts, valeur in enumerate([1120, 1600, 1440, 940], start=1):
            await emit(valeur, ts=ts)

        assert types(service) == ["raised", "escalated", "deescalated",
                                  "resolved"]
        assert service.active() == []
        resolu = service.recent()[0]
        assert resolu["kind"] == "resolved"
        assert resolu["alert"]["value"] == 940
        assert resolu["alert"]["since_ms"] == 1

    async def test_subscribed_to_bus(self, service):
        bus = RecordBus()
        bus.subscribe(service)

        await bus.publish(CO2, make_measurement(1120, offset=1), replay=True)
        assert len(service.active()) == 1
        assert service.recent() == []
        await bus.publish(CO2, make_measurement(1600, timestamp_ms=2000, offset=2))
        assert types(service) == ["escalated"]


class TestActive:
    async def test_critical_first_then_oldest(self, service, emit):
        await emit(1120, ts=300, node_id="w-recent")
        await emit(1120, ts=100, node_id="w-ancien")
        await emit(1600, ts=200, node_id="c-recent")
        await emit(1600, ts=150, node_id="c-ancien")
        await emit(1120, ts=100, node_id="w-ancien-bis")

        assert [a["node_id"] for a in service.active()] == [
            "c-ancien", "c-recent", "w-ancien", "w-ancien-bis", "w-recent"]

    async def test_escalation_keeps_original_start(self, service, emit):
        await emit(1120, ts=100, node_id="a")
        await emit(1600, ts=150, node_id="b")
        await emit(1600, ts=200, node_id="a")

        # a escalade en critical mais son alerte a commence avant celle de b
        assert [a["node_id"] for a in service.active()] == ["a", "b"]


class TestRecent:
    async def test_most_recent_first(self, service, emit):
        await emit(1120, ts=1, node_id="a")
        await emit(1120, ts=2, node_id="b")

        assert [e["alert"]["node_id"] for e in service.recent()] == ["b", "a"]

    async def test_bounded_history(self, service, emit):
        # 101 cycles declenchement / resolution : 202 evenements
        for i in range(101):
            await emit(1120, ts=2 * i)
            await emit(900, ts=2 * i + 1)

        recent = service.recent()
        assert len(recent) == AlertService.RECENT_SIZE == 200
        assert recent[0]["at_ms"] == 201
        assert recent[-1]["at_ms"] == 2


class TestSubscribers:
    async def test_snapshot_on_subscribe(self, service, emit):
        await emit(1120, ts=100, node_id="a")
        await emit(1600, ts=200, node_id="b")

        (snapshot,) = drain(service.subscribe())

        assert snapshot["type"] == "snapshot"
        assert [a["node_id"] for a in snapshot["active"]] == ["b", "a"]

    async def test_events_broadcast_to_subscribers(self, service, emit):
        q1, q2 = service.subscribe(), service.subscribe()

        await emit(1120, ts=100)

        for queue in (q1, q2):
            snapshot, message = drain(queue)
            assert snapshot == {"type": "snapshot", "active": []}
            assert message["type"] == "event"
            assert message["event"] == service.recent()[0]
            assert message["event"]["kind"] == "raised"

    async def test_no_broadcast_without_event(self, service, emit):
        queue = service.subscribe()
        await emit(1120, ts=100)
        await emit(1200, ts=200)  # meme niveau : mise a jour seule

        assert [m["type"] for m in drain(queue)] == ["snapshot", "event"]

    async def test_unsubscribe(self, service, emit):
        queue = service.subscribe()
        service.unsubscribe(queue)
        service.unsubscribe(queue)  # sans erreur s'il est deja desabonne

        await emit(1120, ts=100)

        assert [m["type"] for m in drain(queue)] == ["snapshot"]

    async def test_full_queue_replaced_by_snapshot(self, service,
                                                        emit):
        """Un evenement perdu fausserait la liste d'alertes du client."""
        service.CLIENT_QUEUE_SIZE = 2
        queue = service.subscribe()  # snapshot

        await emit(1120, ts=1)    # raised : la file est pleine
        await emit(1600, ts=2)    # escalated : debordement
        await emit(900, ts=3)     # resolved

        snapshot, resolution = drain(queue)
        assert snapshot["type"] == "snapshot"
        assert [a["severity"] for a in snapshot["active"]] == ["critical"]
        assert resolution["event"]["kind"] == "resolved"
        # L'historique n'est pas affecte
        assert types(service) == ["raised", "escalated", "resolved"]

    async def test_events_independent_of_state(self, service, emit):
        """Evenement diffuse : copie, pas une reference sur l'etat courant."""
        queue = service.subscribe()
        await emit(1120, ts=100)
        await emit(1250, ts=200)

        _, message = drain(queue)
        assert message["event"]["alert"]["value"] == 1120


class TestAcknowledge:
    async def test_acknowledges_active_alert(self, service, emit):
        queue = service.subscribe()
        await emit(1120, ts=100)

        acquittee = service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=150)

        assert (acquittee["acknowledged_by"], acquittee["acknowledged_ms"]) == \
            ("K. Brou", 150)
        assert service.active() == [acquittee]
        assert types(service) == ["raised", "acknowledged"]
        evenement = service.recent()[0]
        assert (evenement["at_ms"], evenement["alert"]) == (150, acquittee)
        assert drain(queue)[-1] == {"type": "event", "event": evenement}

    async def test_not_active(self, service, emit):
        with pytest.raises(LookupError):
            service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=1)
        await emit(1120, ts=100)
        await emit(900, ts=200)
        with pytest.raises(LookupError):
            service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=300)
        with pytest.raises(LookupError):
            service.acknowledge("sans-separateur", "K. Brou", at_ms=300)

    async def test_already_acknowledged(self, service, emit):
        await emit(1120, ts=100)
        service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=150)
        with pytest.raises(ValueError, match="K. Brou"):
            service.acknowledge(f"{CO2}|n1", "M. Diallo", at_ms=160)

    async def test_kept_until_resolved(self, service, emit):
        await emit(1120, ts=100)
        service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=150)
        await emit(1600, ts=200)  # escalade : meme alerte, acquittement garde
        await emit(1700, ts=250)  # mise a jour sans evenement
        assert service.active()[0]["acknowledged_by"] == "K. Brou"

        await emit(900, ts=300)  # resolue : l'evenement porte l'acquittement
        assert service.recent()[0]["alert"]["acknowledged_by"] == "K. Brou"

        await emit(1120, ts=400)  # nouvelle alerte : non acquittee
        assert service.active()[0]["acknowledged_ms"] is None

    async def test_listeners_notified_of_each_event(self, service, emit):
        evenements = []
        service.add_listener(evenements.append)

        await emit(1120, ts=100)
        service.acknowledge(f"{CO2}|n1", "K. Brou", at_ms=150)

        assert [e.kind for e in evenements] == ["raised", "acknowledged"]
        assert evenements == service.recent_events()[::-1]


class TestAccessors:
    async def test_active_by_sensor(self, service, emit):
        await emit(1120, ts=100, node_id="a")
        await emit(900, ts=100, node_id="b")
        assert list(service.active_by_sensor()) == [(CO2, "a")]
        assert service.active_by_sensor()[(CO2, "a")].to_dict() == \
            service.active()[0]

    def test_rules_for(self, service):
        assert [r.threshold for r in service.rules_for(CO2)] == [1000, 1500]
        assert service.rules_for("gridd.obs.occupancy.count") == ()


class TestLogging:
    async def test_levels_per_event_kind(self, service, emit, caplog):
        with caplog.at_level(logging.INFO,
                             logger="app.services.alert_service"):
            for ts, valeur in enumerate([1120, 1600, 1440, 940], start=1):
                await emit(valeur, ts=ts)

        niveaux = {r.getMessage().split("alerte ")[1].split(" ")[0]: r.levelno
                   for r in caplog.records if "alerte " in r.getMessage()}
        assert niveaux == {
            "raised": logging.WARNING,
            "escalated": logging.WARNING,
            "deescalated": logging.INFO,
            "resolved": logging.INFO,
        }

    async def test_message_with_sensor_and_location(self, service, emit,
                                                    caplog):
        with caplog.at_level(logging.WARNING):
            await emit(1120, ts=1, node_id="n9", zone="Zone B")
            await emit(1120, ts=1, node_id="n10", zone=None, space=None)

        assert f"[{CO2}] alerte raised (warning) capteur n9 (Zone B)" in \
            caplog.text
        assert "capteur n10 :" in caplog.text
