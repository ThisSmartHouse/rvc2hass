"""Tests for the Thor Hurricane 35M profile."""

from pathlib import Path

import pytest

from rvc2hass.config import load_profile


PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "thor_hurricane_35m.yaml"


@pytest.fixture(scope="module")
def profile():
    return load_profile(PROFILE_PATH)


class TestEntityCounts:
    """Verify correct entity counts matching current rvc_mqtt package."""

    def test_light_count(self, profile):
        assert len(profile.lights) == 8

    def test_switch_count(self, profile):
        assert len(profile.switches) == 13

    def test_cover_count(self, profile):
        assert len(profile.covers) == 3

    def test_sensor_count(self, profile):
        assert len(profile.sensors) == 20

    def test_binary_sensor_count(self, profile):
        assert len(profile.binary_sensors) == 9


class TestProfileMetadata:
    """Profile metadata matches expected values."""

    def test_name(self, profile):
        assert profile.info.name == "Thor Hurricane 35M"

    def test_manufacturer(self, profile):
        assert profile.info.manufacturer == "Thor Motor Coach"

    def test_model(self, profile):
        assert profile.info.model == "Hurricane 35M"

    def test_year(self, profile):
        assert profile.info.year == 2020

    def test_multiplex(self, profile):
        assert profile.info.multiplex == "Firefly"


class TestInstanceUniqueness:
    """No duplicate instance numbers within an entity type."""

    def test_light_instances_unique(self, profile):
        instances = [lt.instance for lt in profile.lights]
        assert len(instances) == len(set(instances))

    def test_switch_instances_unique(self, profile):
        instances = [sw.instance for sw in profile.switches]
        assert len(instances) == len(set(instances))


class TestLights:
    """Verify light entity details."""

    def test_dimmable_lights(self, profile):
        dimmable = [lt for lt in profile.lights if lt.dimmable]
        assert len(dimmable) == 4
        names = {lt.name for lt in dimmable}
        assert names == {"Living Room", "Bedroom", "Front Bathroom", "Rear Bathroom"}

    def test_non_dimmable_lights(self, profile):
        non_dimmable = [lt for lt in profile.lights if not lt.dimmable]
        assert len(non_dimmable) == 4
        names = {lt.name for lt in non_dimmable}
        assert names == {"Vanity", "Cargo", "Stairwell", "Awning"}


class TestSwitches:
    """Verify switch entity details."""

    def test_generator_switches_use_payload_1(self, profile):
        gen_switches = [sw for sw in profile.switches if "Generator" in sw.name]
        assert len(gen_switches) == 2
        for sw in gen_switches:
            assert sw.payload_on == 1
            assert sw.payload_off == 3

    def test_hvac_switches_use_payload_2(self, profile):
        hvac = [sw for sw in profile.switches if "A/C" in sw.name or sw.name == "Furnace"]
        for sw in hvac:
            assert sw.payload_on == 2


class TestCovers:
    """Verify cover entity details."""

    def test_awning(self, profile):
        awning = [cv for cv in profile.covers if cv.name == "Awning"][0]
        assert awning.extend_instance == 24
        assert awning.retract_instance == 25

    def test_front_slide(self, profile):
        slide = [cv for cv in profile.covers if cv.name == "Front Slide"][0]
        assert slide.extend_instance == 10
        assert slide.retract_instance == 11

    def test_rear_slide(self, profile):
        slide = [cv for cv in profile.covers if cv.name == "Rear Slide"][0]
        assert slide.extend_instance == 12
        assert slide.retract_instance == 13


class TestSensors:
    """Verify sensor entity details."""

    def test_battery_sensors(self, profile):
        batt = [s for s in profile.sensors if "Battery Voltage" in s.name]
        assert len(batt) == 2
        assert all(s.dgn == "DC_SOURCE_STATUS_1" for s in batt)

    def test_temperature_sensors(self, profile):
        temps = [s for s in profile.sensors if s.name.startswith("Temperature")]
        assert len(temps) == 2
        assert all(s.dgn == "THERMOSTAT_AMBIENT_STATUS" for s in temps)

    def test_tank_sensors(self, profile):
        tanks = [s for s in profile.sensors if "Tank" in s.name or s.name == "Propane"]
        assert len(tanks) == 6

    def test_generator_sensors(self, profile):
        gen = [s for s in profile.sensors if s.name.startswith("Generator")]
        assert len(gen) == 3

    def test_thermostat_sensors(self, profile):
        therm = [s for s in profile.sensors if "Climate" in s.name or "Thermostat" in s.name]
        assert len(therm) == 6  # 3 per zone × 2 zones


class TestBinarySensors:
    """Verify binary sensor entity details."""

    def test_generator_running(self, profile):
        gen = [bs for bs in profile.binary_sensors if bs.name == "Generator Running"][0]
        assert gen.dgn == "GENERATOR_STATUS_1"
        assert gen.on_value == 3

    def test_lock_sensors(self, profile):
        locks = [bs for bs in profile.binary_sensors if "Locked" in bs.name]
        assert len(locks) == 8
        for lock in locks:
            assert lock.on_value == "01"
            assert lock.field == "lock status"
