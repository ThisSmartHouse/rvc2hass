"""Configuration and profile loading for rvc2hass.

Handles loading the RV profile YAML which defines what's on this coach's
CAN bus and how to expose it to Home Assistant. Also handles CLI argument
parsing.
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CANConfig:
    """CAN bus connection settings."""
    interface: str = "socketcan"
    channel: str = "can0"
    bitrate: int = 250000


@dataclass
class MQTTConfig:
    """MQTT broker connection settings."""
    broker: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None


@dataclass
class ProfileInfo:
    """RV profile metadata."""
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    year: int = 0
    multiplex: str = ""


@dataclass
class LightEntity:
    """A light entity from the profile."""
    instance: int
    name: str
    dimmable: bool = True


@dataclass
class SwitchEntity:
    """A switch entity from the profile."""
    instance: int
    name: str
    payload_on: int = 2
    payload_off: int = 3


@dataclass
class CoverEntity:
    """A cover entity from the profile."""
    name: str
    extend_instance: int
    retract_instance: int


@dataclass
class SensorEntity:
    """A sensor entity from the profile."""
    dgn: str
    name: str
    instance: int | None = None
    field: str | None = None
    unit: str | None = None
    device_class: str | None = None
    value_template: str | None = None
    value_map: dict[str, str] | None = None


@dataclass
class BinarySensorEntity:
    """A binary sensor entity from the profile."""
    dgn: str
    name: str
    instance: int | None = None
    field: str | None = None
    on_value: Any = None


@dataclass
class Profile:
    """Complete RV profile loaded from YAML."""
    info: ProfileInfo = field(default_factory=ProfileInfo)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    can: CANConfig = field(default_factory=CANConfig)
    lights: list[LightEntity] = field(default_factory=list)
    switches: list[SwitchEntity] = field(default_factory=list)
    covers: list[CoverEntity] = field(default_factory=list)
    sensors: list[SensorEntity] = field(default_factory=list)
    binary_sensors: list[BinarySensorEntity] = field(default_factory=list)


def load_profile(path: Path) -> Profile:
    """Load an RV profile from a YAML file.

    Args:
        path: Path to the profile YAML file.

    Returns:
        A fully populated Profile instance.

    Raises:
        FileNotFoundError: If the profile file doesn't exist.
        ValueError: If required fields are missing or invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Profile must be a YAML mapping, got {type(raw).__name__}")

    # Profile metadata
    profile_raw = raw.get("profile", {})
    if not profile_raw.get("name"):
        raise ValueError("Profile must have a 'profile.name' field")

    info = ProfileInfo(
        name=profile_raw.get("name", ""),
        manufacturer=profile_raw.get("manufacturer", ""),
        model=profile_raw.get("model", ""),
        year=profile_raw.get("year", 0),
        multiplex=profile_raw.get("multiplex", ""),
    )

    # MQTT config
    mqtt_raw = raw.get("mqtt", {})
    mqtt = MQTTConfig(
        broker=mqtt_raw.get("broker", "localhost"),
        port=mqtt_raw.get("port", 1883),
        username=mqtt_raw.get("username"),
        password=mqtt_raw.get("password"),
    )

    # CAN config
    can_raw = raw.get("can", {})
    can = CANConfig(
        interface=can_raw.get("interface", "socketcan"),
        channel=can_raw.get("channel", "can0"),
        bitrate=can_raw.get("bitrate", 250000),
    )

    # Entity lists
    lights = [
        LightEntity(
            instance=lt["instance"],
            name=lt["name"],
            dimmable=lt.get("dimmable", True),
        )
        for lt in raw.get("lights", [])
    ]

    switches = [
        SwitchEntity(
            instance=sw["instance"],
            name=sw["name"],
            payload_on=sw.get("payload_on", 2),
            payload_off=sw.get("payload_off", 3),
        )
        for sw in raw.get("switches", [])
    ]

    covers = [
        CoverEntity(
            name=cv["name"],
            extend_instance=cv["extend_instance"],
            retract_instance=cv["retract_instance"],
        )
        for cv in raw.get("covers", [])
    ]

    sensors = [
        SensorEntity(
            dgn=sn["dgn"],
            name=sn["name"],
            instance=sn.get("instance"),
            field=sn.get("field"),
            unit=sn.get("unit"),
            device_class=sn.get("device_class"),
            value_template=sn.get("value_template"),
            value_map=sn.get("value_map"),
        )
        for sn in raw.get("sensors", [])
    ]

    binary_sensors = [
        BinarySensorEntity(
            dgn=bs["dgn"],
            name=bs["name"],
            instance=bs.get("instance"),
            field=bs.get("field"),
            on_value=bs.get("on_value"),
        )
        for bs in raw.get("binary_sensors", [])
    ]

    return Profile(
        info=info,
        mqtt=mqtt,
        can=can,
        lights=lights,
        switches=switches,
        covers=covers,
        sensors=sensors,
        binary_sensors=binary_sensors,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog="rvc2hass",
        description="RV-C CAN bus to Home Assistant via MQTT auto-discovery",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Path to the RV profile YAML file",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Path to the RV-C spec YAML (default: specs/rvc_spec.yaml relative to install)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Run in discovery mode: scan the bus and report what's there",
    )
    parser.add_argument(
        "--discover-duration",
        type=int,
        default=60,
        help="Duration in seconds for discovery scan (default: 60)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)
