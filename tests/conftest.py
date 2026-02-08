"""Shared test fixtures for rvc2hass tests."""

import tempfile
from pathlib import Path

import pytest
import yaml


MINIMAL_PROFILE = {
    "profile": {
        "name": "Test RV",
        "manufacturer": "Test Mfg",
        "model": "Test 100",
        "year": 2024,
    },
    "mqtt": {"broker": "localhost", "port": 1883},
    "can": {"interface": "socketcan", "channel": "can0", "bitrate": 250000},
    "lights": [
        {"instance": 17, "name": "Living Room", "dimmable": True},
    ],
    "switches": [
        {"instance": 1, "name": "Front A/C", "payload_on": 2, "payload_off": 3},
    ],
    "covers": [
        {"name": "Awning", "extend_instance": 24, "retract_instance": 25},
    ],
    "sensors": [
        {"dgn": "DC_SOURCE_STATUS_1", "instance": 1, "name": "House Battery Voltage",
         "field": "dc voltage", "unit": "V", "device_class": "voltage"},
    ],
    "binary_sensors": [
        {"dgn": "GENERATOR_STATUS_1", "name": "Generator Running",
         "field": "status", "on_value": 3},
    ],
}


@pytest.fixture
def minimal_profile_path(tmp_path):
    """Write a minimal valid profile to a temp file and return its path."""
    p = tmp_path / "test_profile.yaml"
    p.write_text(yaml.dump(MINIMAL_PROFILE))
    return p


@pytest.fixture
def spec_dir():
    """Return the path to the specs directory."""
    return Path(__file__).parent.parent / "specs"


@pytest.fixture
def profiles_dir():
    """Return the path to the profiles directory."""
    return Path(__file__).parent.parent / "profiles"
