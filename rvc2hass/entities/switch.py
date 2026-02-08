"""Switch entity command handling.

Switches use the same DC_DIMMER_COMMAND_2 as lights but with different
command values (payload_on/payload_off from the profile).
"""

from __future__ import annotations

from .light import build_dimmer_command


def build_switch_on(instance: int, payload_on: int = 2) -> list[tuple[int, bytes]]:
    """Build CAN frame(s) to turn a switch on."""
    return [build_dimmer_command(instance, payload_on)]


def build_switch_off(instance: int, payload_off: int = 3) -> list[tuple[int, bytes]]:
    """Build CAN frame(s) to turn a switch off."""
    return [build_dimmer_command(instance, payload_off, brightness=0)]
