"""Cover entity command handling.

Covers (slides, awning) use two DC dimmer instances — one for extend,
one for retract. Sending "on" to the extend instance opens, sending "on"
to the retract instance closes. Sending "off" to both stops movement.
"""

from .light import build_cover_command


def build_cover_open(extend_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to open (extend) a cover."""
    return build_cover_command(extend_instance, activate=True)


def build_cover_close(retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to close (retract) a cover."""
    return build_cover_command(retract_instance, activate=True)


def build_cover_stop(extend_instance: int, retract_instance: int) -> list[tuple[int, bytes]]:
    """Build CAN frames to stop cover movement."""
    return (
        build_cover_command(extend_instance, activate=False) +
        build_cover_command(retract_instance, activate=False)
    )
