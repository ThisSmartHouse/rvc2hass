"""Entity manager — routes decoded RV-C messages to MQTT state updates.

Maps decoded CAN frames to the appropriate entity based on DGN + instance,
then publishes the state update to the correct MQTT topic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import Profile
from .mqtt_client import STATE_PREFIX, slugify

log = logging.getLogger(__name__)


class EntityManager:
    """Routes decoded RV-C data to MQTT state topics."""

    def __init__(self, profile: Profile, publish_fn):
        """
        Args:
            profile: The loaded RV profile.
            publish_fn: Callable(topic, payload, retain=False) for MQTT publishing.
        """
        self.profile = profile
        self.publish = publish_fn
        self._build_lookup()

    def _build_lookup(self):
        """Build lookup tables from profile for fast message routing."""
        # Light instances → LightEntity
        self._lights = {lt.instance: lt for lt in self.profile.lights}
        # Switch instances → SwitchEntity
        self._switches = {sw.instance: sw for sw in self.profile.switches}
        # Cover instances → (CoverEntity, "extend"|"retract")
        self._cover_instances: dict[int, tuple] = {}
        for cv in self.profile.covers:
            self._cover_instances[cv.extend_instance] = (cv, "extend")
            self._cover_instances[cv.retract_instance] = (cv, "retract")
        # Sensors by (dgn_name, instance) or (dgn_name, None)
        self._sensors: dict[tuple, list] = {}
        for sn in self.profile.sensors:
            key = (sn.dgn, sn.instance)
            self._sensors.setdefault(key, []).append(sn)
        # Binary sensors by (dgn_name, instance) or (dgn_name, None)
        self._binary_sensors: dict[tuple, list] = {}
        for bs in self.profile.binary_sensors:
            key = (bs.dgn, bs.instance)
            self._binary_sensors.setdefault(key, []).append(bs)

    def process_decoded(self, decoded: dict[str, Any]):
        """Process a decoded RV-C message and publish state updates.

        Args:
            decoded: Dictionary from rvc_decoder.decode_frame().
        """
        dgn_name = decoded.get("name", "")
        instance = decoded.get("instance")

        # Route DC_DIMMER_STATUS_3 to lights, switches, covers, and binary sensors
        if dgn_name == "DC_DIMMER_STATUS_3" and instance is not None:
            self._handle_dimmer_status(instance, decoded)

        # Route sensors
        for key in [(dgn_name, instance), (dgn_name, None)]:
            for sensor in self._sensors.get(key, []):
                self._handle_sensor(sensor, decoded)
            for bs in self._binary_sensors.get(key, []):
                self._handle_binary_sensor(bs, decoded)

    def _handle_dimmer_status(self, instance: int, decoded: dict):
        """Handle DC_DIMMER_STATUS_3 for lights, switches, covers."""
        brightness_raw = decoded.get("operating status (brightness)")
        brightness = brightness_raw if brightness_raw != "n/a" else 0

        # Light
        if instance in self._lights:
            light = self._lights[instance]
            is_on = brightness is not None and brightness > 0
            self.publish(
                f"{STATE_PREFIX}/light/{instance}/state",
                "ON" if is_on else "OFF",
            )
            if light.dimmable and brightness is not None:
                self.publish(
                    f"{STATE_PREFIX}/light/{instance}/brightness/state",
                    str(int(brightness)),
                )

        # Switch
        if instance in self._switches:
            is_on = brightness is not None and brightness > 0
            self.publish(
                f"{STATE_PREFIX}/switch/{instance}/state",
                "ON" if is_on else "OFF",
            )

        # Cover
        if instance in self._cover_instances:
            cover, direction = self._cover_instances[instance]
            # Covers don't have a simple state — we track extend/retract activity
            # The cover state topic uses the cover's slug
            slug = slugify(cover.name)
            is_active = brightness is not None and brightness > 0
            if is_active:
                state = "opening" if direction == "extend" else "closing"
            else:
                state = "open" if direction == "extend" else "closed"
            self.publish(f"{STATE_PREFIX}/cover/{slug}/state", state)

    def _handle_sensor(self, sensor, decoded: dict):
        """Publish a sensor state update."""
        slug = slugify(sensor.name)
        instance_suffix = f"_{sensor.instance}" if sensor.instance is not None else ""

        if sensor.field:
            value = decoded.get(sensor.field)
        elif sensor.value_template:
            # For template sensors like tanks, compute from decoded fields
            value = self._eval_sensor_template(sensor, decoded)
        else:
            value = None

        if value is None:
            return

        # Apply value map if present
        if sensor.value_map and value in sensor.value_map:
            value = sensor.value_map[value]
        elif sensor.value_map:
            # Try string key lookup
            str_value = str(value)
            if str_value in sensor.value_map:
                value = sensor.value_map[str_value]

        topic = f"{STATE_PREFIX}/sensor/{slug}{instance_suffix}/state"

        if sensor.value_template:
            self.publish(topic, json.dumps({"value": value}))
        else:
            self.publish(topic, str(value))

    def _eval_sensor_template(self, sensor, decoded: dict) -> Any:
        """Evaluate a simple sensor value template."""
        template = sensor.value_template
        if not template:
            return None

        if template == "relative_level / resolution * 100":
            rl = decoded.get("relative level")
            res = decoded.get("resolution")
            if rl is not None and res is not None and res != 0:
                return round(rl / res * 100)
            return None

        if template == "value / 60":
            value = decoded.get(sensor.field) if sensor.field else None
            if value is not None:
                return round(value / 60, 1)
            return None

        if template == "voltage_to_soc":
            voltage = decoded.get(sensor.field) if sensor.field else None
            if voltage is not None and voltage != "n/a":
                return self._voltage_to_soc(voltage)
            return None

        return None

    def _voltage_to_soc(self, voltage: float) -> int:
        """Convert lead-acid battery voltage to SoC percentage.

        Uses the same lookup table as the current HA template.
        """
        if voltage >= 12.89:
            return 100
        elif voltage >= 12.78:
            return 90
        elif voltage >= 12.65:
            return 80
        elif voltage >= 12.51:
            return 70
        elif voltage >= 12.41:
            return 60
        elif voltage >= 12.31:
            return 50
        elif voltage >= 12.21:
            return 40
        elif voltage >= 12.11:
            return 30
        elif voltage >= 12.0:
            return 20
        elif voltage >= 11.9:
            return 10
        else:
            return 0

    def _handle_binary_sensor(self, bs, decoded: dict):
        """Publish a binary sensor state update."""
        slug = slugify(bs.name)
        instance_suffix = f"_{bs.instance}" if bs.instance is not None else ""

        value = decoded.get(bs.field) if bs.field else None
        if value is None:
            return

        is_on = (value == bs.on_value)
        topic = f"{STATE_PREFIX}/binary_sensor/{slug}{instance_suffix}/state"
        self.publish(topic, "ON" if is_on else "OFF")
