"""Cover entity command handling.

Covers (slides, awning) use two DC dimmer instances — one for extend,
one for retract. Sending "on" to the extend instance opens, sending "on"
to the retract instance closes.

OPEN/CLOSE deactivation uses off (cmd 3) on BOTH instances to clear
any stale interlock — whether from the opposite direction (auto-stop
after full retract) or the same direction (manual stop during extend).
NOTE: stop (cmd 21) must NOT be used for covers — it causes Firefly to
briefly re-activate the motor at near-100% brightness.  CAN status noise
from the deactivation is handled by cover suppression in entity_manager,
which ignores CAN frames for a cover while a command is in flight.

STOP uses plain off (cmd 3) to both instances, which is sufficient to
halt a currently-running motor.

Open/close are split into separate deactivate and activate frame lists
so the app handler can insert a short delay between them, giving Firefly
time to process the deactivation before the activation arrives.
"""

from __future__ import annotations

from .light import build_cover_activate, build_cover_deactivate, build_dimmer_command


def build_cover_open_deactivate(extend_instance: int, retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to deactivate both directions before opening."""
    return (
        build_cover_deactivate(retract_instance) +
        build_cover_deactivate(extend_instance)
    )


def build_cover_open_activate(extend_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to activate the extend direction."""
    return build_cover_activate(extend_instance)


def build_cover_close_deactivate(extend_instance: int, retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to deactivate both directions before closing."""
    return (
        build_cover_deactivate(extend_instance) +
        build_cover_deactivate(retract_instance)
    )


def build_cover_close_activate(retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to activate the retract direction."""
    return build_cover_activate(retract_instance)


def build_cover_stop(extend_instance: int, retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to stop cover movement.

    Plain off (cmd 3) to both — sufficient to halt a running motor
    without triggering brief re-activation on the inactive instance.
    """
    return [
        build_dimmer_command(extend_instance, 3, brightness=0),
        build_dimmer_command(retract_instance, 3, brightness=0),
    ]
