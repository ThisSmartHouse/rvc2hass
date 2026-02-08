"""Tests for the RV-C protocol spec YAML."""

from pathlib import Path

import pytest
import yaml


SPEC_PATH = Path(__file__).parent.parent / "specs" / "rvc_spec.yaml"


@pytest.fixture(scope="module")
def spec():
    """Load the spec YAML once for all tests."""
    with open(SPEC_PATH) as f:
        return yaml.safe_load(f)


class TestSpecLoads:
    """Basic loading and structure validation."""

    def test_spec_loads_without_error(self, spec):
        assert isinstance(spec, dict)

    def test_has_api_version(self, spec):
        assert "API_VERSION" in spec

    def test_dgn_count(self, spec):
        """Spec should have ~200+ DGN definitions (excluding API_VERSION and Z aliases)."""
        dgn_keys = [k for k in spec if k not in ("API_VERSION",)]
        assert len(dgn_keys) >= 200


class TestDGNStructure:
    """Every DGN must have required fields."""

    def test_all_dgns_have_name(self, spec):
        for dgn_id, dgn in spec.items():
            if dgn_id == "API_VERSION":
                continue
            assert "name" in dgn, f"DGN {dgn_id} missing 'name'"

    def test_dgns_with_parameters_have_valid_structure(self, spec):
        for dgn_id, dgn in spec.items():
            if dgn_id == "API_VERSION":
                continue
            if "parameters" not in dgn:
                # DGNs without parameters are either aliases or stubs — that's ok
                continue
            params = dgn["parameters"]
            assert isinstance(params, list), f"DGN {dgn_id} parameters must be a list"
            for i, param in enumerate(params):
                assert "byte" in param, (
                    f"DGN {dgn_id} parameter {i} missing 'byte'"
                )

    def test_parameters_have_names(self, spec):
        """Parameters should have name fields (except ascii type which may not)."""
        for dgn_id, dgn in spec.items():
            if dgn_id == "API_VERSION":
                continue
            for param in dgn.get("parameters", []):
                param_type = param.get("type", "")
                if param_type == "ascii":
                    continue
                assert "name" in param, (
                    f"DGN {dgn_id} has parameter at byte {param.get('byte')} without name"
                )


class TestKeyDGNs:
    """Spot-check key DGNs used by our profile match expected structure."""

    def test_dc_dimmer_status_3(self, spec):
        dgn = spec["1FEDA"]
        assert dgn["name"] == "DC_DIMMER_STATUS_3"
        params = {p["name"]: p for p in dgn["parameters"] if "name" in p}
        assert "instance" in params
        assert "operating status (brightness)" in params
        assert params["operating status (brightness)"]["unit"] == "Pct"
        assert "lock status" in params

    def test_dc_dimmer_command_2(self, spec):
        dgn = spec["1FEDB"]
        assert dgn["name"] == "DC_DIMMER_COMMAND_2"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "command" in params
        assert "desired level" in params
        # Verify command values include our key ones
        cmd_values = params["command"]["values"]
        assert cmd_values[2] == "on delay"
        assert cmd_values[3] == "off"
        assert cmd_values[17] == "ramp brightness"

    def test_dc_source_status_1(self, spec):
        dgn = spec["1FFFD"]
        assert dgn["name"] == "DC_SOURCE_STATUS_1"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "dc voltage" in params
        assert params["dc voltage"]["type"] == "uint16"
        assert params["dc voltage"]["unit"] == "V"
        assert "dc current" in params
        assert params["dc current"]["type"] == "uint32"
        assert params["dc current"]["unit"] == "A"

    def test_tank_status(self, spec):
        dgn = spec["1FFB7"]
        assert dgn["name"] == "TANK_STATUS"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "relative level" in params
        assert "resolution" in params
        # Verify instance values include expected tank types
        inst_values = params["instance"]["values"]
        assert inst_values[0] == "fresh water"
        assert inst_values[1] == "black waste"
        assert inst_values[3] == "lpg"

    def test_thermostat_status_1(self, spec):
        dgn = spec["1FFE2"]
        assert dgn["name"] == "THERMOSTAT_STATUS_1"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "operating mode" in params
        assert "fan speed" in params
        assert params["fan speed"]["unit"] == "Pct"

    def test_thermostat_ambient_status(self, spec):
        dgn = spec["1FF9C"]
        assert dgn["name"] == "THERMOSTAT_AMBIENT_STATUS"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "ambient temp" in params
        assert params["ambient temp"]["unit"] == "Deg C"
        assert params["ambient temp"]["type"] == "uint16"

    def test_generator_status_1(self, spec):
        dgn = spec["1FFDC"]
        assert dgn["name"] == "GENERATOR_STATUS_1"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "status" in params
        assert "engine run time" in params
        assert "engine load" in params
        # Verify status values
        status_values = params["status"]["values"]
        assert status_values[0] == "stopped"
        assert status_values[3] == "running"
        assert status_values[5] == "fault"

    def test_waterheater_status(self, spec):
        dgn = spec["1FFF7"]
        assert dgn["name"] == "WATERHEATER_STATUS"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "water temperature" in params
        assert "operating modes" in params

    def test_charger_status(self, spec):
        dgn = spec["1FFC7"]
        assert dgn["name"] == "CHARGER_STATUS"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "charge voltage" in params
        assert "charge current" in params

    def test_inverter_status(self, spec):
        dgn = spec["1FFD4"]
        assert dgn["name"] == "INVERTER_STATUS"
        params = {p["name"]: p for p in dgn["parameters"]}
        assert "instance" in params
        assert "status" in params


class TestAliases:
    """DGNs with alias fields should reference valid DGNs."""

    def test_aliases_reference_valid_dgns(self, spec):
        for dgn_id, dgn in spec.items():
            if dgn_id == "API_VERSION":
                continue
            alias = dgn.get("alias")
            if alias:
                assert alias in spec, (
                    f"DGN {dgn_id} ({dgn['name']}) aliases {alias} which doesn't exist"
                )

    def test_set_date_time_aliases_date_time(self, spec):
        assert spec["1FFFE"]["alias"] == "1FFFF"
        assert spec["1FFFF"]["name"] == "DATE_TIME_STATUS"
