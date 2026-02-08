"""MQTT client for Home Assistant auto-discovery and state publishing.

Handles:
- Publishing discovery configs (retained) so HA auto-creates entities
- Publishing state updates as CAN frames arrive
- Subscribing to command topics for write-path control
- LWT (Last Will and Testament) for availability tracking
"""

import json
import logging
import re
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import (
    BinarySensorEntity,
    CoverEntity,
    LightEntity,
    MQTTConfig,
    Profile,
    SensorEntity,
    SwitchEntity,
)

log = logging.getLogger(__name__)

# MQTT topic prefixes
STATE_PREFIX = "rvc2hass"
DISCOVERY_PREFIX = "homeassistant"
AVAILABILITY_TOPIC = f"{STATE_PREFIX}/status"


def slugify(name: str) -> str:
    """Convert a name to a slug suitable for MQTT topics and unique IDs."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class MQTTManager:
    """Manages MQTT connection, discovery, and state publishing."""

    def __init__(self, profile: Profile):
        self.profile = profile
        self._client: mqtt.Client | None = None
        self._command_callbacks: dict[str, Callable] = {}
        self._connected = False

    def _make_device(self) -> dict:
        """Build the HA device info block shared by all entities."""
        return {
            "identifiers": ["rvc2hass"],
            "name": "RV-C Bus",
            "manufacturer": self.profile.info.manufacturer,
            "model": self.profile.info.model,
        }

    def connect(self):
        """Connect to the MQTT broker."""
        cfg = self.profile.mqtt
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="rvc2hass",
        )
        # Set LWT before connecting
        self._client.will_set(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)

        if cfg.username:
            self._client.username_pw_set(cfg.username, cfg.password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        log.info("Connecting to MQTT broker %s:%d", cfg.broker, cfg.port)
        self._client.connect(cfg.broker, cfg.port)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("MQTT connected")
            self._connected = True
            # Publish online status
            self._client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
            # Re-subscribe to command topics on reconnect
            for topic in self._command_callbacks:
                self._client.subscribe(topic)
        else:
            log.error("MQTT connection failed with code %d", rc)

    def _on_message(self, client, userdata, msg):
        callback = self._command_callbacks.get(msg.topic)
        if callback:
            callback(msg.topic, msg.payload.decode("utf-8"))

    def disconnect(self):
        """Disconnect from the MQTT broker."""
        if self._client:
            self._client.publish(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            log.info("MQTT disconnected")

    def subscribe_command(self, topic: str, callback: Callable):
        """Subscribe to a command topic with a callback."""
        self._command_callbacks[topic] = callback
        if self._client and self._connected:
            self._client.subscribe(topic)

    def publish(self, topic: str, payload: str, retain: bool = False):
        """Publish a message."""
        if self._client:
            self._client.publish(topic, payload, retain=retain)

    def publish_discovery(self):
        """Publish all HA MQTT auto-discovery configs from the profile."""
        device = self._make_device()

        for light in self.profile.lights:
            self._publish_light_discovery(light, device)
        for switch in self.profile.switches:
            self._publish_switch_discovery(switch, device)
        for cover in self.profile.covers:
            self._publish_cover_discovery(cover, device)
        for sensor in self.profile.sensors:
            self._publish_sensor_discovery(sensor, device)
        for bs in self.profile.binary_sensors:
            self._publish_binary_sensor_discovery(bs, device)

        total = (len(self.profile.lights) + len(self.profile.switches) +
                 len(self.profile.covers) + len(self.profile.sensors) +
                 len(self.profile.binary_sensors))
        log.info("Published %d discovery configs", total)

    def _publish_light_discovery(self, light: LightEntity, device: dict):
        slug = slugify(light.name)
        unique_id = f"rvc_light_{slug}_{light.instance}"
        config = {
            "name": light.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/light/{light.instance}/set",
            "state_topic": f"{STATE_PREFIX}/light/{light.instance}/state",
            "schema": "default",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        if light.dimmable:
            config["brightness_command_topic"] = f"{STATE_PREFIX}/light/{light.instance}/brightness/set"
            config["brightness_state_topic"] = f"{STATE_PREFIX}/light/{light.instance}/brightness/state"
            config["brightness_scale"] = 100
            config["on_command_type"] = "brightness"

        topic = f"{DISCOVERY_PREFIX}/light/rvc_{slug}/config"
        self.publish(topic, json.dumps(config), retain=True)

    def _publish_switch_discovery(self, switch: SwitchEntity, device: dict):
        slug = slugify(switch.name)
        unique_id = f"rvc_switch_{slug}_{switch.instance}"
        config = {
            "name": switch.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/switch/{switch.instance}/set",
            "state_topic": f"{STATE_PREFIX}/switch/{switch.instance}/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        topic = f"{DISCOVERY_PREFIX}/switch/rvc_{slug}/config"
        self.publish(topic, json.dumps(config), retain=True)

    def _publish_cover_discovery(self, cover: CoverEntity, device: dict):
        slug = slugify(cover.name)
        unique_id = f"rvc_cover_{slug}"
        config = {
            "name": cover.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/cover/{slug}/set",
            "state_topic": f"{STATE_PREFIX}/cover/{slug}/state",
            "payload_open": "OPEN",
            "payload_close": "CLOSE",
            "payload_stop": "STOP",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        topic = f"{DISCOVERY_PREFIX}/cover/rvc_{slug}/config"
        self.publish(topic, json.dumps(config), retain=True)

    def _publish_sensor_discovery(self, sensor: SensorEntity, device: dict):
        slug = slugify(sensor.name)
        instance_suffix = f"_{sensor.instance}" if sensor.instance is not None else ""
        unique_id = f"rvc_sensor_{slug}{instance_suffix}"
        state_topic = f"{STATE_PREFIX}/sensor/{slug}{instance_suffix}/state"
        config: dict[str, Any] = {
            "name": sensor.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "state_topic": state_topic,
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        if sensor.unit:
            config["unit_of_measurement"] = sensor.unit
        if sensor.device_class:
            config["device_class"] = sensor.device_class
        if sensor.value_template:
            config["value_template"] = "{{ value_json.value }}"

        topic = f"{DISCOVERY_PREFIX}/sensor/rvc_{slug}/config"
        self.publish(topic, json.dumps(config), retain=True)

    def _publish_binary_sensor_discovery(self, bs: BinarySensorEntity, device: dict):
        slug = slugify(bs.name)
        instance_suffix = f"_{bs.instance}" if bs.instance is not None else ""
        unique_id = f"rvc_binary_sensor_{slug}{instance_suffix}"
        state_topic = f"{STATE_PREFIX}/binary_sensor/{slug}{instance_suffix}/state"
        config = {
            "name": bs.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        topic = f"{DISCOVERY_PREFIX}/binary_sensor/rvc_{slug}/config"
        self.publish(topic, json.dumps(config), retain=True)


def generate_discovery_configs(profile: Profile) -> list[tuple[str, dict]]:
    """Generate all discovery config topic/payload pairs without publishing.

    Useful for testing. Returns list of (topic, config_dict) tuples.
    """
    manager = MQTTManager(profile)
    configs = []
    device = manager._make_device()

    for light in profile.lights:
        slug = slugify(light.name)
        unique_id = f"rvc_light_{slug}_{light.instance}"
        config: dict[str, Any] = {
            "name": light.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/light/{light.instance}/set",
            "state_topic": f"{STATE_PREFIX}/light/{light.instance}/state",
            "schema": "default",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        if light.dimmable:
            config["brightness_command_topic"] = f"{STATE_PREFIX}/light/{light.instance}/brightness/set"
            config["brightness_state_topic"] = f"{STATE_PREFIX}/light/{light.instance}/brightness/state"
            config["brightness_scale"] = 100
            config["on_command_type"] = "brightness"
        configs.append((f"{DISCOVERY_PREFIX}/light/rvc_{slug}/config", config))

    for switch in profile.switches:
        slug = slugify(switch.name)
        unique_id = f"rvc_switch_{slug}_{switch.instance}"
        config = {
            "name": switch.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/switch/{switch.instance}/set",
            "state_topic": f"{STATE_PREFIX}/switch/{switch.instance}/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        configs.append((f"{DISCOVERY_PREFIX}/switch/rvc_{slug}/config", config))

    for cover in profile.covers:
        slug = slugify(cover.name)
        unique_id = f"rvc_cover_{slug}"
        config = {
            "name": cover.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "command_topic": f"{STATE_PREFIX}/cover/{slug}/set",
            "state_topic": f"{STATE_PREFIX}/cover/{slug}/state",
            "payload_open": "OPEN",
            "payload_close": "CLOSE",
            "payload_stop": "STOP",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        configs.append((f"{DISCOVERY_PREFIX}/cover/rvc_{slug}/config", config))

    for sensor in profile.sensors:
        slug = slugify(sensor.name)
        instance_suffix = f"_{sensor.instance}" if sensor.instance is not None else ""
        unique_id = f"rvc_sensor_{slug}{instance_suffix}"
        state_topic = f"{STATE_PREFIX}/sensor/{slug}{instance_suffix}/state"
        config = {
            "name": sensor.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "state_topic": state_topic,
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        if sensor.unit:
            config["unit_of_measurement"] = sensor.unit
        if sensor.device_class:
            config["device_class"] = sensor.device_class
        configs.append((f"{DISCOVERY_PREFIX}/sensor/rvc_{slug}/config", config))

    for bs in profile.binary_sensors:
        slug = slugify(bs.name)
        instance_suffix = f"_{bs.instance}" if bs.instance is not None else ""
        unique_id = f"rvc_binary_sensor_{slug}{instance_suffix}"
        state_topic = f"{STATE_PREFIX}/binary_sensor/{slug}{instance_suffix}/state"
        config = {
            "name": bs.name,
            "unique_id": unique_id,
            "object_id": f"rvc_{slug}",
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        configs.append((f"{DISCOVERY_PREFIX}/binary_sensor/rvc_{slug}/config", config))

    return configs
