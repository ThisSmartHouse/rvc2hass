"""Tests for MQTT auto-discovery and state publishing."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rvc2hass.config import LightEntity, Profile, load_profile
from rvc2hass.entity_manager import EntityManager
from rvc2hass.mqtt_client import (
    AVAILABILITY_TOPIC,
    DISCOVERY_PREFIX,
    STATE_PREFIX,
    generate_discovery_configs,
    slugify,
)


PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "thor_hurricane_35m.yaml"


@pytest.fixture(scope="module")
def profile():
    return load_profile(PROFILE_PATH)


@pytest.fixture(scope="module")
def configs(profile):
    return generate_discovery_configs(profile)


class TestSlugify:
    def test_simple(self):
        assert slugify("Living Room") == "living_room"

    def test_special_chars(self):
        assert slugify("Front A/C Compressor") == "front_a_c_compressor"

    def test_spaces(self):
        assert slugify("Gas Water Heater") == "gas_water_heater"


class TestDiscoveryLightDimmable:
    """Dimmable light discovery has all required fields."""

    def test_has_required_fields(self, configs):
        # Find the bedroom light (dimmable)
        bedroom = [c for t, c in configs if "bedroom" in t and "light" in t][0]
        assert "command_topic" in bedroom
        assert "state_topic" in bedroom
        assert "brightness_command_topic" in bedroom
        assert "brightness_state_topic" in bedroom
        assert bedroom["brightness_scale"] == 100
        assert "unique_id" in bedroom
        assert "device" in bedroom
        assert "availability_topic" in bedroom
        assert bedroom["on_command_type"] == "brightness"

    def test_topics_use_instance(self, configs):
        bedroom = [c for t, c in configs if "bedroom" in t and "light" in t][0]
        assert bedroom["command_topic"] == f"{STATE_PREFIX}/light/18/set"
        assert bedroom["state_topic"] == f"{STATE_PREFIX}/light/18/state"
        assert bedroom["brightness_command_topic"] == f"{STATE_PREFIX}/light/18/brightness/set"


class TestDiscoveryLightNonDimmable:
    """Non-dimmable light has on/off but no brightness."""

    def test_no_brightness_topics(self, configs):
        cargo = [c for t, c in configs if "cargo" in t and "light" in t][0]
        assert "command_topic" in cargo
        assert "state_topic" in cargo
        assert "brightness_command_topic" not in cargo
        assert "brightness_state_topic" not in cargo
        assert "on_command_type" not in cargo


class TestDiscoverySwitch:
    """Switch discovery has correct fields."""

    def test_switch_has_required_fields(self, configs):
        furnace = [c for t, c in configs if "furnace" in t and "switch" in t][0]
        assert "command_topic" in furnace
        assert "state_topic" in furnace
        assert furnace["payload_on"] == "ON"
        assert furnace["payload_off"] == "OFF"
        assert "unique_id" in furnace


class TestDiscoverySensor:
    """Sensor discovery has correct fields."""

    def test_voltage_sensor(self, configs):
        house_batt = [c for t, c in configs
                      if "house_battery_voltage" in t and "sensor" in t][0]
        assert "state_topic" in house_batt
        assert house_batt["unit_of_measurement"] == "V"
        assert house_batt["device_class"] == "voltage"

    def test_tank_sensor(self, configs):
        fresh = [c for t, c in configs
                 if "freshwater" in t and "sensor" in t][0]
        assert "state_topic" in fresh
        assert fresh["unit_of_measurement"] == "%"

    def test_generator_status_sensor(self, configs):
        gen = [c for t, c in configs
               if "generator_status" in t and "sensor" in t][0]
        assert "state_topic" in gen


class TestDiscoveryBinarySensor:
    """Binary sensor discovery has correct fields."""

    def test_generator_running(self, configs):
        gen = [c for t, c in configs
               if "generator_running" in t and "binary_sensor" in t][0]
        assert "state_topic" in gen
        assert gen["payload_on"] == "ON"
        assert gen["payload_off"] == "OFF"


class TestDiscoveryCover:
    """Cover discovery has correct fields."""

    def test_awning_cover(self, configs):
        awning = [c for t, c in configs
                  if "awning" in t and "cover" in t][0]
        assert "command_topic" in awning
        assert "state_topic" in awning
        assert awning["payload_open"] == "OPEN"
        assert awning["payload_close"] == "CLOSE"
        assert awning["payload_stop"] == "STOP"


class TestDiscoveryUniqueIds:
    """All unique IDs must be globally unique."""

    def test_all_unique_ids_unique(self, configs):
        ids = [c["unique_id"] for _, c in configs]
        assert len(ids) == len(set(ids)), f"Duplicate unique_ids found: {[x for x in ids if ids.count(x) > 1]}"


class TestDiscoveryDeviceGrouping:
    """All entities reference the same device for HA grouping."""

    def test_all_same_device(self, configs):
        devices = [c["device"] for _, c in configs]
        first = devices[0]
        for d in devices:
            assert d == first


class TestLWT:
    """MQTT LWT configuration."""

    def test_availability_topic(self, configs):
        for _, config in configs:
            assert config["availability_topic"] == AVAILABILITY_TOPIC
            assert config["payload_available"] == "online"
            assert config["payload_not_available"] == "offline"


class TestEntityManagerStatePublish:
    """EntityManager publishes correct state updates."""

    def setup_method(self):
        self.published = []
        self.profile = load_profile(PROFILE_PATH)
        self.manager = EntityManager(
            self.profile,
            lambda topic, payload, **kw: self.published.append((topic, payload)),
        )

    def test_light_state_on(self):
        """Dimmer brightness > 0 publishes ON."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 18,
            "operating status (brightness)": 50.0,
            "lock status": "00",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/light/18/state"] == "ON"
        assert states[f"{STATE_PREFIX}/light/18/brightness/state"] == "50"

    def test_light_state_off(self):
        """Dimmer brightness 0 publishes OFF."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 18,
            "operating status (brightness)": 0.0,
            "lock status": "00",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/light/18/state"] == "OFF"

    def test_switch_state(self):
        """Dimmer status for a switch instance publishes ON/OFF."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 29,
            "operating status (brightness)": 50.0,
            "lock status": "00",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/switch/29/state"] == "ON"

    def test_sensor_voltage(self):
        """DC_SOURCE_STATUS_1 publishes voltage."""
        self.manager.process_decoded({
            "name": "DC_SOURCE_STATUS_1",
            "instance": 1,
            "dc voltage": 13.2,
            "dc current": 5.0,
        })
        states = {t: p for t, p in self.published}
        assert f"{STATE_PREFIX}/sensor/house_battery_voltage_1/state" in states
        assert states[f"{STATE_PREFIX}/sensor/house_battery_voltage_1/state"] == "13.2"

    def test_binary_sensor_generator(self):
        """GENERATOR_STATUS_1 with status 3 publishes ON for generator running."""
        self.manager.process_decoded({
            "name": "GENERATOR_STATUS_1",
            "status": 3,
            "engine run time": 1200,
            "engine load": 50.0,
        })
        # Find generator running binary sensor
        gen_topics = [t for t, p in self.published if "generator_running" in t]
        assert len(gen_topics) > 0
        states = {t: p for t, p in self.published}
        assert states[gen_topics[0]] == "ON"

    def test_binary_sensor_lock(self):
        """Lock status '01' publishes ON."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 24,
            "operating status (brightness)": 0.0,
            "lock status": "01",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/binary_sensor/awning_extend_locked_24/state"] == "ON"

    def test_cover_opening(self):
        """Extend instance active → opening."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 24,
            "operating status (brightness)": 50.0,
            "lock status": "00",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/cover/awning/state"] == "opening"

    def test_cover_closing(self):
        """Retract instance active → closing."""
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 25,
            "operating status (brightness)": 50.0,
            "lock status": "00",
        })
        states = {t: p for t, p in self.published}
        assert states[f"{STATE_PREFIX}/cover/awning/state"] == "closing"

    def test_cover_stopped_no_bounce(self):
        """Both instances inactive → stopped, and no bouncing between states."""
        # Send extend instance (inactive)
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 24,
            "operating status (brightness)": 0.0,
            "lock status": "00",
        })
        # Send retract instance (inactive)
        self.manager.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 25,
            "operating status (brightness)": 0.0,
            "lock status": "00",
        })
        # Only cover state updates (filter out binary sensor updates)
        cover_states = [p for t, p in self.published if t == f"{STATE_PREFIX}/cover/awning/state"]
        # Should have published "stopped" only once (deduplication)
        assert cover_states == ["stopped"]

    def test_cover_no_republish_on_same_state(self):
        """Repeated frames with same activity don't republish."""
        for _ in range(5):
            self.manager.process_decoded({
                "name": "DC_DIMMER_STATUS_3",
                "instance": 24,
                "operating status (brightness)": 0.0,
                "lock status": "00",
            })
            self.manager.process_decoded({
                "name": "DC_DIMMER_STATUS_3",
                "instance": 25,
                "operating status (brightness)": 0.0,
                "lock status": "00",
            })
        cover_states = [p for t, p in self.published if t == f"{STATE_PREFIX}/cover/awning/state"]
        # Should publish "stopped" exactly once despite 10 frames
        assert cover_states == ["stopped"]

    def test_tank_sensor(self):
        """TANK_STATUS publishes computed percentage."""
        self.manager.process_decoded({
            "name": "TANK_STATUS",
            "instance": 0,
            "relative level": 180,
            "resolution": 240,
        })
        states = {t: p for t, p in self.published}
        topic = f"{STATE_PREFIX}/sensor/freshwater_tank_0/state"
        assert topic in states
        import json
        data = json.loads(states[topic])
        assert data["value"] == 75  # 180/240*100 = 75


class TestLightSuppression:
    """EntityManager suppresses light status during brightness ramps."""

    def setup_method(self):
        self.published = []
        self.profile = Profile(
            lights=[
                LightEntity(instance=17, name="Living Room", dimmable=True),
                LightEntity(instance=18, name="Bedroom", dimmable=True),
            ],
        )
        self.manager = EntityManager(
            self.profile,
            lambda topic, payload, **kw: self.published.append((topic, payload)),
        )

    def _dimmer_status(self, instance, brightness):
        return {
            "name": "DC_DIMMER_STATUS_3",
            "instance": instance,
            "operating status (brightness)": brightness,
            "lock status": "00",
        }

    def test_suppressed_light_ignores_can_status(self):
        """A suppressed instance should not publish state from CAN frames."""
        self.manager.suppress_light(17)
        self.manager.process_decoded(self._dimmer_status(17, 100.0))
        light_states = [p for t, p in self.published if "/light/17/" in t]
        assert light_states == []

    def test_unsuppressed_light_publishes_normally(self):
        """After unsuppressing, CAN status should publish again."""
        self.manager.suppress_light(17)
        self.manager.process_decoded(self._dimmer_status(17, 100.0))
        self.manager.unsuppress_light(17)
        self.manager.process_decoded(self._dimmer_status(17, 50.0))
        light_states = [(t, p) for t, p in self.published if "/light/17/" in t]
        assert len(light_states) == 2  # state ON + brightness 50
        states = {t: p for t, p in light_states}
        assert states[f"{STATE_PREFIX}/light/17/state"] == "ON"
        assert states[f"{STATE_PREFIX}/light/17/brightness/state"] == "50"

    def test_suppression_only_affects_target_instance(self):
        """Suppressing instance 17 should not block instance 18."""
        self.manager.suppress_light(17)
        self.manager.process_decoded(self._dimmer_status(18, 75.0))
        light_18 = [(t, p) for t, p in self.published if "/light/18/" in t]
        assert len(light_18) == 2  # state + brightness

    def test_unsuppress_without_suppress_is_safe(self):
        """Calling unsuppress on a non-suppressed instance should not error."""
        self.manager.unsuppress_light(17)  # no-op, should not raise


class TestRampTimerCancellation:
    """OFF and new brightness commands cancel pending ramp timers."""

    def setup_method(self):
        self.published = []
        self.sent_frames = []
        self.profile = Profile(
            lights=[
                LightEntity(instance=17, name="Living Room", dimmable=True),
            ],
        )
        self.entity_mgr = EntityManager(
            self.profile,
            lambda topic, payload, **kw: self.published.append((topic, payload)),
        )
        self.mock_mqtt = MagicMock()
        self.mock_mqtt.publish = MagicMock(
            side_effect=lambda topic, payload, **kw: self.published.append((topic, payload))
        )
        self.mock_can = MagicMock()
        self.mock_can.send = MagicMock(
            side_effect=lambda arb_id, data: self.sent_frames.append((arb_id, data))
        )

    def _setup_and_get_handlers(self):
        """Run _setup_commands and extract the registered handlers."""
        from rvc2hass.app import _setup_commands
        _setup_commands(self.profile, self.mock_mqtt, self.mock_can, self.entity_mgr)
        # Collect handlers keyed by topic from subscribe_command calls
        handlers = {}
        for call in self.mock_mqtt.subscribe_command.call_args_list:
            topic, handler = call[0]
            handlers[topic] = handler
        return handlers

    def test_off_cancels_ramp_timer(self):
        """Turning off during a ramp should cancel the stop+lock timer."""
        import threading
        handlers = self._setup_and_get_handlers()
        brightness_handler = handlers[f"{STATE_PREFIX}/light/17/brightness/set"]
        on_off_handler = handlers[f"{STATE_PREFIX}/light/17/set"]

        # Start a brightness ramp
        brightness_handler(f"{STATE_PREFIX}/light/17/brightness/set", "100")

        # Instance should be suppressed now
        assert 17 in self.entity_mgr._suppressed_lights

        # Turn off immediately
        on_off_handler(f"{STATE_PREFIX}/light/17/set", "OFF")

        # Suppression should be lifted (timer cancelled)
        assert 17 not in self.entity_mgr._suppressed_lights

        # Wait long enough for the timer to have fired if it wasn't cancelled
        import time
        time.sleep(0.1)  # timers are 5s, so if not cancelled this won't trigger

        # The off command should have sent its frame
        off_frames = [f for f in self.sent_frames if f[1][3] == 3]  # command=3 is off
        assert len(off_frames) == 1

    def test_new_brightness_cancels_previous_timer(self):
        """A second brightness command should cancel the first timer."""
        handlers = self._setup_and_get_handlers()
        brightness_handler = handlers[f"{STATE_PREFIX}/light/17/brightness/set"]

        # Send two brightness commands quickly
        brightness_handler(f"{STATE_PREFIX}/light/17/brightness/set", "100")
        brightness_handler(f"{STATE_PREFIX}/light/17/brightness/set", "50")

        # Instance should still be suppressed (second timer active)
        assert 17 in self.entity_mgr._suppressed_lights

        # Should have sent exactly 2 ramp commands (command=17)
        ramp_frames = [f for f in self.sent_frames if f[1][3] == 17]
        assert len(ramp_frames) == 2
        # First ramp: brightness 100*2=200, second: 50*2=100
        assert ramp_frames[0][1][2] == 200
        assert ramp_frames[1][1][2] == 100

    def test_suppression_active_during_ramp(self):
        """CAN status should be suppressed while ramp timer is pending."""
        handlers = self._setup_and_get_handlers()
        brightness_handler = handlers[f"{STATE_PREFIX}/light/17/brightness/set"]

        # Start a brightness ramp to 10%
        brightness_handler(f"{STATE_PREFIX}/light/17/brightness/set", "10")
        self.published.clear()

        # Simulate a stale CAN frame arriving at old brightness
        self.entity_mgr.process_decoded({
            "name": "DC_DIMMER_STATUS_3",
            "instance": 17,
            "operating status (brightness)": 100.0,
            "lock status": "00",
        })

        # Should NOT have published the stale 100% brightness
        brightness_pubs = [p for t, p in self.published
                          if t == f"{STATE_PREFIX}/light/17/brightness/state"]
        assert brightness_pubs == []


class TestOnMessageExceptionHandling:
    """Verify _on_message catches callback exceptions to protect the paho thread."""

    def test_callback_exception_does_not_propagate(self):
        """An exception in a command callback must not propagate out of _on_message."""
        from rvc2hass.mqtt_client import MQTTManager
        from rvc2hass.config import load_profile

        profile = load_profile(PROFILE_PATH)
        mgr = MQTTManager(profile)

        def exploding_callback(topic, payload):
            raise OSError("No buffer space available")

        mgr._command_callbacks["rvc2hass/light/17/set"] = exploding_callback

        fake_msg = MagicMock()
        fake_msg.topic = "rvc2hass/light/17/set"
        fake_msg.payload = b"OFF"

        # Must not raise — an unhandled exception here would kill the paho thread
        mgr._on_message(None, None, fake_msg)
