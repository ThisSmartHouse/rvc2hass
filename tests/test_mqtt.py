"""Tests for MQTT auto-discovery and state publishing."""

from pathlib import Path

import pytest

from rvc2hass.config import load_profile
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
