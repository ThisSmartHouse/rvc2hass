"""Light entity command handling.

Builds DC_DIMMER_COMMAND_2 CAN frames for light control, ported from
CoachProxy's dc_dimmer.pl.

CAN frame layout for DC_DIMMER_COMMAND_2 (DGN 1FEDB):
  Byte 0: Instance number
  Byte 1: Group (0xFF = all groups)
  Byte 2: Desired brightness level (0-200, where level = percentage * 2)
  Byte 3: Command (1=on, 2=on-delay, 3=off, 17=ramp brightness, etc.)
  Byte 4: Delay/Duration (0xFF = no delay)
  Byte 5: Interlock (0x00 = none)
  Byte 6-7: Reserved (0xFF)

Arbitration ID: priority=6, DGN=1FEDB, source=0x63 (99)
  Binary: 110 0 11111 11101 1011 01100011
  Hex: 0x19FEDB63
"""

from __future__ import annotations

DC_DIMMER_COMMAND_2_ARB_ID = 0x19FEDB63
SOURCE_ADDRESS = 0x63  # 99 decimal


def build_dimmer_command(instance: int, command: int,
                         brightness: int = 100, duration: int = 0xFF) -> tuple[int, bytes]:
    """Build a DC_DIMMER_COMMAND_2 CAN frame.

    Args:
        instance: Dimmer instance number (1-99).
        command: Command byte (1=on, 2=on-delay, 3=off, 17=ramp, etc.).
        brightness: Brightness 0-100 (will be doubled for CAN encoding).
        duration: Delay/duration byte (0xFF = no delay).

    Returns:
        Tuple of (arbitration_id, data_bytes).
    """
    data = bytes([
        instance,
        0xFF,               # group: all
        brightness * 2,     # brightness * 2 for CAN encoding
        command,
        duration,
        0x00,               # interlock: none
        0xFF,               # reserved
        0xFF,               # reserved
    ])
    return DC_DIMMER_COMMAND_2_ARB_ID, data


def build_on_command(instance: int, payload_on: int = 2) -> list[tuple[int, bytes]]:
    """Build CAN frame(s) to turn a dimmer on.

    Args:
        instance: Dimmer instance number.
        payload_on: Command byte for "on" (1 or 2, varies by device type).

    Returns:
        List of (arbitration_id, data_bytes) tuples to send.
    """
    return [build_dimmer_command(instance, payload_on)]


def build_off_command(instance: int, payload_off: int = 3) -> list[tuple[int, bytes]]:
    """Build CAN frame(s) to turn a dimmer off."""
    return [build_dimmer_command(instance, payload_off, brightness=0)]


def build_brightness_ramp(instance: int, brightness: int) -> tuple[int, bytes]:
    """Build the initial ramp command for setting dimmer brightness.

    Returns a single CAN frame. After sending, the caller must wait ~5 seconds
    for the Firefly to ramp to the target, then send the stop+lock frames
    from build_brightness_stop().

    Args:
        instance: Dimmer instance number.
        brightness: Target brightness 0-100.
    """
    return build_dimmer_command(instance, 17, brightness)


def build_brightness_stop(instance: int) -> list[tuple[int, bytes]]:
    """Build stop + lock frames to finalize a brightness ramp.

    Send these ~5 seconds after the ramp command to lock in the brightness.
    """
    return [
        build_dimmer_command(instance, 21, brightness=0, duration=0),
        build_dimmer_command(instance, 4, brightness=0, duration=0),
    ]


def build_cover_activate(instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frame to activate a cover direction (extend or retract).

    Args:
        instance: Dimmer instance for extend or retract.

    Returns:
        List of (arbitration_id, data_bytes) tuples.
    """
    return [build_dimmer_command(instance, 1, brightness=100)]


def build_cover_deactivate(instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to deactivate a cover direction.

    Uses off (cmd 3) to deactivate.  NOTE: stop (cmd 21) must NOT be used
    for covers — it causes Firefly to briefly re-activate the motor at
    near-100% brightness, which triggers the hardware interlock when both
    directions get pulsed simultaneously.

    Args:
        instance: Dimmer instance for extend or retract.

    Returns:
        List of (arbitration_id, data_bytes) tuples.
    """
    return [build_dimmer_command(instance, 3, brightness=0)]
