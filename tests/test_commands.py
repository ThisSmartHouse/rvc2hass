"""Tests for command encoding (write path).

Validates that CAN frames are built correctly for lights, switches, and covers,
matching the behavior of CoachProxy's dc_dimmer.pl.
"""

import pytest

from rvc2hass.entities.light import (
    DC_DIMMER_COMMAND_2_ARB_ID,
    build_brightness_ramp,
    build_brightness_stop,
    build_dimmer_command,
    build_off_command,
    build_on_command,
    build_cover_command,
)
from rvc2hass.entities.switch import build_switch_on, build_switch_off
from rvc2hass.entities.cover import build_cover_open, build_cover_close, build_cover_stop


class TestDimmerCommand:
    """Low-level DC_DIMMER_COMMAND_2 frame building."""

    def test_arbitration_id(self):
        arb_id, _ = build_dimmer_command(18, 2)
        assert arb_id == 0x19FEDB63

    def test_instance_byte(self):
        _, data = build_dimmer_command(18, 2)
        assert data[0] == 18  # instance

    def test_group_byte(self):
        _, data = build_dimmer_command(18, 2)
        assert data[1] == 0xFF  # all groups

    def test_brightness_doubled(self):
        _, data = build_dimmer_command(18, 2, brightness=75)
        assert data[2] == 150  # 75 * 2

    def test_command_byte(self):
        _, data = build_dimmer_command(18, 2)
        assert data[3] == 2

    def test_duration_byte(self):
        _, data = build_dimmer_command(18, 2, duration=120)
        assert data[4] == 120

    def test_default_duration(self):
        _, data = build_dimmer_command(18, 2)
        assert data[4] == 0xFF

    def test_reserved_bytes(self):
        _, data = build_dimmer_command(18, 2)
        assert data[5] == 0x00  # interlock
        assert data[6] == 0xFF  # reserved
        assert data[7] == 0xFF  # reserved

    def test_data_length(self):
        _, data = build_dimmer_command(18, 2)
        assert len(data) == 8


class TestDimmerOn:
    """Command 2 (on) for instance 18."""

    def test_on_command(self):
        frames = build_on_command(18, payload_on=2)
        assert len(frames) == 1
        arb_id, data = frames[0]
        assert arb_id == 0x19FEDB63
        assert data[0] == 18       # instance
        assert data[1] == 0xFF     # group
        assert data[2] == 200      # 100 * 2 (default brightness)
        assert data[3] == 2        # command: on-delay
        assert data[4] == 0xFF     # duration
        assert data[5] == 0x00
        assert data[6] == 0xFF
        assert data[7] == 0xFF


class TestDimmerOff:
    """Command 3 (off) for instance 18."""

    def test_off_command(self):
        frames = build_off_command(18, payload_off=3)
        assert len(frames) == 1
        _, data = frames[0]
        assert data[0] == 18
        assert data[2] == 0        # brightness 0
        assert data[3] == 3        # command: off


class TestDimmerBrightness:
    """Ramp brightness command (17) with follow-up stop (21) and lock (4).

    The ramp and stop/lock are now split into separate functions because
    the Firefly needs ~5 seconds between them to reach target brightness.
    """

    def test_ramp_frame(self):
        arb_id, data = build_brightness_ramp(18, 75)
        assert data[0] == 18       # instance
        assert data[2] == 150      # 75 * 2
        assert data[3] == 17       # command: ramp brightness

    def test_stop_returns_two_frames(self):
        frames = build_brightness_stop(18)
        assert len(frames) == 2

    def test_stop_command(self):
        frames = build_brightness_stop(18)
        _, data = frames[0]
        assert data[0] == 18
        assert data[2] == 0        # brightness 0
        assert data[3] == 21       # command: ramp up/down (stop)
        assert data[4] == 0        # duration 0

    def test_lock_command(self):
        frames = build_brightness_stop(18)
        _, data = frames[1]
        assert data[0] == 18
        assert data[3] == 4        # command: stop (lock)


class TestCoverOpenClose:
    """Cover commands using extend/retract instances."""

    def test_cover_open(self):
        frames = build_cover_open(24)  # awning extend
        assert len(frames) == 1
        _, data = frames[0]
        assert data[0] == 24       # extend instance
        assert data[2] == 200      # brightness 100*2
        assert data[3] == 1        # command: on duration

    def test_cover_close(self):
        frames = build_cover_close(25)  # awning retract
        assert len(frames) == 1
        _, data = frames[0]
        assert data[0] == 25       # retract instance
        assert data[3] == 1        # command: on duration

    def test_cover_stop(self):
        frames = build_cover_stop(24, 25)  # awning
        assert len(frames) == 2
        # Both extend and retract get deactivated
        _, data1 = frames[0]
        _, data2 = frames[1]
        assert data1[0] == 24      # extend instance
        assert data1[3] == 3       # command: off
        assert data2[0] == 25      # retract instance
        assert data2[3] == 3       # command: off


class TestSwitchCommands:
    """Switch on/off commands."""

    def test_switch_on_payload_2(self):
        frames = build_switch_on(29, payload_on=2)
        _, data = frames[0]
        assert data[0] == 29       # furnace instance
        assert data[3] == 2        # command

    def test_switch_on_payload_1(self):
        frames = build_switch_on(34, payload_on=1)
        _, data = frames[0]
        assert data[0] == 34       # generator start instance
        assert data[3] == 1        # command

    def test_switch_off(self):
        frames = build_switch_off(29, payload_off=3)
        _, data = frames[0]
        assert data[0] == 29
        assert data[3] == 3        # command: off
