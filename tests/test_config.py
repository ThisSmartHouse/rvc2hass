"""Tests for configuration and profile loading."""

from pathlib import Path

import pytest
import yaml

from rvc2hass.config import load_profile, parse_args, Profile


class TestParseArgs:
    """CLI argument parsing tests."""

    def test_profile_required(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_profile_arg(self, tmp_path):
        args = parse_args(["--profile", str(tmp_path / "p.yaml")])
        assert args.profile == tmp_path / "p.yaml"
        assert not args.discover
        assert not args.debug

    def test_discover_flag(self, tmp_path):
        args = parse_args(["--profile", str(tmp_path / "p.yaml"), "--discover"])
        assert args.discover is True

    def test_debug_flag(self, tmp_path):
        args = parse_args(["--profile", str(tmp_path / "p.yaml"), "--debug"])
        assert args.debug is True

    def test_discover_duration(self, tmp_path):
        args = parse_args([
            "--profile", str(tmp_path / "p.yaml"),
            "--discover", "--discover-duration", "120",
        ])
        assert args.discover_duration == 120

    def test_discover_duration_default(self, tmp_path):
        args = parse_args(["--profile", str(tmp_path / "p.yaml")])
        assert args.discover_duration == 60

    def test_spec_arg(self, tmp_path):
        args = parse_args([
            "--profile", str(tmp_path / "p.yaml"),
            "--spec", str(tmp_path / "spec.yaml"),
        ])
        assert args.spec == tmp_path / "spec.yaml"


class TestLoadProfile:
    """Profile YAML loading tests."""

    def test_load_valid_profile(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert isinstance(profile, Profile)
        assert profile.info.name == "Test RV"
        assert profile.info.manufacturer == "Test Mfg"
        assert profile.info.model == "Test 100"
        assert profile.info.year == 2024

    def test_mqtt_config(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert profile.mqtt.broker == "localhost"
        assert profile.mqtt.port == 1883

    def test_can_config(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert profile.can.interface == "socketcan"
        assert profile.can.channel == "can0"
        assert profile.can.bitrate == 250000

    def test_lights(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert len(profile.lights) == 1
        assert profile.lights[0].instance == 17
        assert profile.lights[0].name == "Living Room"
        assert profile.lights[0].dimmable is True

    def test_switches(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert len(profile.switches) == 1
        assert profile.switches[0].instance == 1
        assert profile.switches[0].payload_on == 2
        assert profile.switches[0].payload_off == 3

    def test_covers(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert len(profile.covers) == 1
        assert profile.covers[0].name == "Awning"
        assert profile.covers[0].extend_instance == 24
        assert profile.covers[0].retract_instance == 25

    def test_sensors(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert len(profile.sensors) == 1
        assert profile.sensors[0].dgn == "DC_SOURCE_STATUS_1"
        assert profile.sensors[0].device_class == "voltage"

    def test_binary_sensors(self, minimal_profile_path):
        profile = load_profile(minimal_profile_path)
        assert len(profile.binary_sensors) == 1
        assert profile.binary_sensors[0].on_value == 3

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Profile not found"):
            load_profile(tmp_path / "nonexistent.yaml")

    def test_missing_profile_name(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(yaml.dump({"profile": {"manufacturer": "X"}}))
        with pytest.raises(ValueError, match="profile.name"):
            load_profile(p)

    def test_invalid_yaml_type(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("just a string")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_profile(p)

    def test_empty_entity_lists(self, tmp_path):
        p = tmp_path / "minimal.yaml"
        p.write_text(yaml.dump({"profile": {"name": "Bare"}}))
        profile = load_profile(p)
        assert profile.lights == []
        assert profile.switches == []
        assert profile.covers == []
        assert profile.sensors == []
        assert profile.binary_sensors == []

    def test_default_switch_payloads(self, tmp_path):
        p = tmp_path / "sw.yaml"
        p.write_text(yaml.dump({
            "profile": {"name": "Test"},
            "switches": [{"instance": 1, "name": "Test Switch"}],
        }))
        profile = load_profile(p)
        assert profile.switches[0].payload_on == 2
        assert profile.switches[0].payload_off == 3

    def test_sensor_with_value_map(self, tmp_path):
        p = tmp_path / "vmap.yaml"
        p.write_text(yaml.dump({
            "profile": {"name": "Test"},
            "sensors": [{
                "dgn": "GENERATOR_STATUS_1",
                "name": "Gen Status",
                "field": "status",
                "value_map": {0: "stopped", 3: "running"},
            }],
        }))
        profile = load_profile(p)
        assert profile.sensors[0].value_map[0] == "stopped"
        assert profile.sensors[0].value_map[3] == "running"
