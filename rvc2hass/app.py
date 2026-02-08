"""Main application loop — ties CAN reading, decoding, MQTT, and commands together.

This is the async main loop that:
1. Connects to MQTT and publishes discovery configs
2. Connects to CAN bus and starts reading frames
3. Decodes each frame and routes to entity manager for state publishing
4. Subscribes to MQTT command topics and sends CAN frames on command
"""

import asyncio
import logging
import signal
from pathlib import Path

import can

from .can_bus import CANBusReader
from .config import Profile
from .entity_manager import EntityManager
from .entities.light import build_brightness_command, build_off_command, build_on_command
from .entities.switch import build_switch_on, build_switch_off
from .entities.cover import build_cover_open, build_cover_close, build_cover_stop
from .mqtt_client import STATE_PREFIX, MQTTManager, slugify
from .rvc_decoder import RvcSpec, decode_frame

log = logging.getLogger(__name__)


def run_service(profile: Profile, args):
    """Run the main rvc2hass service."""

    spec_path = args.spec or Path(__file__).parent.parent / "specs" / "rvc_spec.yaml"
    spec = RvcSpec(spec_path)

    mqtt = MQTTManager(profile)
    can_reader = CANBusReader(
        interface=profile.can.interface,
        channel=profile.can.channel,
        bitrate=profile.can.bitrate,
    )

    entity_mgr = EntityManager(profile, mqtt.publish)

    # Connect MQTT and publish discovery
    mqtt.connect()
    import time
    time.sleep(1)  # Wait for MQTT connection
    mqtt.publish_discovery()

    # Set up command subscriptions
    _setup_commands(profile, mqtt, can_reader)

    # Frame handler
    def on_frame(msg: can.Message):
        data_hex = msg.data.hex().upper().ljust(16, '0')[:16]
        decoded = decode_frame(msg.arbitration_id, data_hex, spec)
        if not decoded["name"].startswith("UNKNOWN"):
            entity_mgr.process_decoded(decoded)

    # Run the main loop
    async def main_loop():
        loop = asyncio.get_event_loop()
        stop_event = asyncio.Event()

        def handle_signal():
            log.info("Shutdown signal received")
            stop_event.set()
            can_reader.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

        # Start reading CAN frames
        read_task = asyncio.create_task(can_reader.read_frames(on_frame))

        # Wait for shutdown
        await stop_event.wait()
        read_task.cancel()

        mqtt.disconnect()
        log.info("Service stopped")

    asyncio.run(main_loop())


def _setup_commands(profile, mqtt, can_reader):
    """Subscribe to MQTT command topics and wire up CAN frame sending."""

    def send_frames(frames: list[tuple[int, bytes]]):
        """Send a list of CAN frames with a small delay between them."""
        for arb_id, data in frames:
            can_reader.send(arb_id, data)

    # Light commands
    for light in profile.lights:
        inst = light.instance
        # On/off
        def make_light_handler(lt):
            def handler(topic, payload):
                if payload == "ON":
                    send_frames(build_on_command(lt.instance))
                elif payload == "OFF":
                    send_frames(build_off_command(lt.instance))
            return handler
        mqtt.subscribe_command(
            f"{STATE_PREFIX}/light/{inst}/set",
            make_light_handler(light),
        )

        # Brightness (dimmable only)
        if light.dimmable:
            def make_brightness_handler(lt):
                def handler(topic, payload):
                    try:
                        brightness = int(float(payload))
                        send_frames(build_brightness_command(lt.instance, brightness))
                    except (ValueError, TypeError):
                        log.warning("Invalid brightness value: %s", payload)
                return handler
            mqtt.subscribe_command(
                f"{STATE_PREFIX}/light/{inst}/brightness/set",
                make_brightness_handler(light),
            )

    # Switch commands
    for switch in profile.switches:
        def make_switch_handler(sw):
            def handler(topic, payload):
                if payload == "ON":
                    send_frames(build_switch_on(sw.instance, sw.payload_on))
                elif payload == "OFF":
                    send_frames(build_switch_off(sw.instance, sw.payload_off))
            return handler
        mqtt.subscribe_command(
            f"{STATE_PREFIX}/switch/{switch.instance}/set",
            make_switch_handler(switch),
        )

    # Cover commands
    for cover in profile.covers:
        slug = slugify(cover.name)

        def make_cover_handler(cv):
            def handler(topic, payload):
                if payload == "OPEN":
                    send_frames(build_cover_open(cv.extend_instance))
                elif payload == "CLOSE":
                    send_frames(build_cover_close(cv.retract_instance))
                elif payload == "STOP":
                    send_frames(build_cover_stop(cv.extend_instance, cv.retract_instance))
            return handler
        mqtt.subscribe_command(
            f"{STATE_PREFIX}/cover/{slug}/set",
            make_cover_handler(cover),
        )
