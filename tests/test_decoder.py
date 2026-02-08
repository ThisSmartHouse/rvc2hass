"""Tests for the RV-C protocol decoder."""

from pathlib import Path

import pytest

from rvc2hass.rvc_decoder import (
    RvcSpec,
    convert_unit,
    decode,
    decode_frame,
    get_bits,
    get_bytes,
    parse_can_id,
)


SPEC_PATH = Path(__file__).parent.parent / "specs" / "rvc_spec.yaml"


@pytest.fixture(scope="module")
def spec():
    return RvcSpec(SPEC_PATH)


class TestParseCanId:
    """CAN arbitration ID parsing."""

    def test_dimmer_status_frame(self):
        # 0x19FEDA9F → priority=6, DGN=1FEDA, src=0x9F
        priority, dgn, src = parse_can_id(0x19FEDA9F)
        assert priority == 6
        assert dgn == "1FEDA"
        assert src == 0x9F

    def test_dc_source_frame(self):
        # 0x19FFFD42 → priority=6, DGN=1FFFD, src=0x42
        priority, dgn, src = parse_can_id(0x19FFFD42)
        assert priority == 6
        assert dgn == "1FFFD"
        assert src == 0x42

    def test_tank_status_frame(self):
        # 0x19FFB744 → priority=6, DGN=1FFB7, src=0x44
        priority, dgn, src = parse_can_id(0x19FFB744)
        assert priority == 6
        assert dgn == "1FFB7"
        assert src == 0x44

    def test_generator_status_frame(self):
        # 0x19FFDC40 → priority=6, DGN=1FFDC, src=0x40
        priority, dgn, src = parse_can_id(0x19FFDC40)
        assert priority == 6
        assert dgn == "1FFDC"
        assert src == 0x40

    def test_thermostat_ambient(self):
        priority, dgn, src = parse_can_id(0x19FF9C44)
        assert priority == 6
        assert dgn == "1FF9C"
        assert src == 0x44

    def test_zero_source(self):
        priority, dgn, src = parse_can_id(0x19FEDA00)
        assert src == 0
        assert dgn == "1FEDA"

    def test_different_priority(self):
        # Priority 3 (binary 011) in bits 28-26
        arb_id = 0x0DFEDA42  # 011 0 11111 11101 1010 01000010
        priority, dgn, src = parse_can_id(arb_id)
        assert priority == 3


class TestGetBytes:
    """Byte extraction with little-endian swap."""

    def test_single_byte(self):
        assert get_bytes("020064C524C52400", "0") == "02"

    def test_single_byte_middle(self):
        assert get_bytes("020064C524C52400", "2") == "64"

    def test_two_byte_range_swapped(self):
        # Bytes 2-3 of "020064C524C52400" = "64C5"
        # Swapped (little-endian): "C564"
        assert get_bytes("020064C524C52400", "2-3") == "C564"

    def test_four_byte_range(self):
        # Bytes 4-7 of "020064C524C52400" = "24C52400"
        # Swapped: "0024C524"
        assert get_bytes("020064C524C52400", "4-7") == "0024C524"

    def test_first_byte(self):
        assert get_bytes("FF00112233445566", "0") == "FF"

    def test_last_byte(self):
        assert get_bytes("0011223344556677", "7") == "77"


class TestGetBits:
    """Bit extraction from hex bytes."""

    def test_bit_0_1(self):
        # 0xC5 = 11000101 in binary
        # Bits 0-1 (LSB end): extract from position 6-7 → "01"
        result = get_bits("C5", "0-1")
        assert result == "01"

    def test_bit_2_3(self):
        # 0xC5 = 11000101
        # Bits 2-3: position 4-5 → "01"
        result = get_bits("C5", "2-3")
        assert result == "01"

    def test_bit_6_7(self):
        # 0xC5 = 11000101
        # Bits 6-7: position 0-1 → "11"
        result = get_bits("C5", "6-7")
        assert result == "11"

    def test_single_bit(self):
        # 0xFF = 11111111
        result = get_bits("FF", "0")
        assert result == "1"

    def test_all_zeros(self):
        result = get_bits("00", "0-7")
        assert result == "00000000"

    def test_all_ones(self):
        result = get_bits("FF", "0-7")
        assert result == "11111111"


class TestConvertUnit:
    """Unit conversions per RV-C Table 5.3."""

    def test_pct_normal(self):
        assert convert_unit(128, "pct", "uint8") == 64.0

    def test_pct_full(self):
        assert convert_unit(200, "pct", "uint8") == 100.0

    def test_pct_na(self):
        assert convert_unit(255, "pct", "uint8") == "n/a"

    def test_temp_uint8(self):
        # 65 - 40 = 25°C
        assert convert_unit(65, "Deg C", "uint8") == 25

    def test_temp_uint8_na(self):
        assert convert_unit(255, "Deg C", "uint8") == "n/a"

    def test_temp_uint16(self):
        # value * 0.03125 - 273
        # 9504 * 0.03125 - 273 = 297 - 273 = 24.0
        result = convert_unit(9504, "Deg C", "uint16")
        assert result == 24.0

    def test_temp_uint16_na(self):
        assert convert_unit(65535, "Deg C", "uint16") == "n/a"

    def test_voltage_uint8(self):
        assert convert_unit(12, "V", "uint8") == 12

    def test_voltage_uint16(self):
        # 2560 * 0.05 = 128.0
        assert convert_unit(2560, "V", "uint16") == 128.0

    def test_voltage_uint16_na(self):
        assert convert_unit(65535, "V", "uint16") == "n/a"

    def test_current_uint8(self):
        assert convert_unit(10, "A", "uint8") == 10

    def test_current_uint16(self):
        # 32100 * 0.05 - 1600 = 1605 - 1600 = 5.0
        assert convert_unit(32100, "A", "uint16") == 5.0

    def test_current_uint16_na(self):
        assert convert_unit(65535, "A", "uint16") == "n/a"

    def test_current_uint32(self):
        # 2000001000 * 0.001 - 2000000 = 2000001.0 - 2000000 = 1.0
        assert convert_unit(2000001000, "A", "uint32") == 1.0

    def test_current_uint32_na(self):
        assert convert_unit(4294967295, "A", "uint32") == "n/a"

    def test_hz_uint16(self):
        # 7680 / 128 = 60.0
        assert convert_unit(7680, "Hz", "uint16") == 60.0

    def test_sec_uint8_normal(self):
        assert convert_unit(120, "sec", "uint8") == 120

    def test_sec_uint8_minutes(self):
        # 245 is in 240-251 range: ((245-240)+4)*60 = 9*60 = 540
        assert convert_unit(245, "sec", "uint8") == 540

    def test_sec_uint16(self):
        assert convert_unit(30, "sec", "uint16") == 60

    def test_bitmap(self):
        assert convert_unit(0xC5, "bitmap", "uint8") == "11000101"


class TestDecode:
    """Full frame decoding with spec."""

    def test_dc_dimmer_status_3(self, spec):
        # Instance 18 (bedroom light), brightness 50% (100 raw → 50.0 pct)
        result = decode("1FEDA", "1200640200FFFFFF", spec)
        assert result["name"] == "DC_DIMMER_STATUS_3"
        assert result["instance"] == 18
        assert result["operating status (brightness)"] == 50.0

    def test_dc_source_voltage(self, spec):
        # Instance 1 (house battery)
        # Bytes 2-3: voltage uint16. If raw hex bytes [2]=0x20, [3]=0x03 →
        # hex string "2003", get_bytes swaps → "0320", int = 800, * 0.05 = 40.0V
        # (not a realistic voltage but tests the math)
        result = decode("1FFFD", "0100200300000000", spec)
        assert result["name"] == "DC_SOURCE_STATUS_1"
        assert result["instance"] == 1
        assert result["dc voltage"] == 40.0

    def test_tank_status(self, spec):
        # Instance 0 (freshwater), relative_level=180, resolution=240
        result = decode("1FFB7", "00B4F0FFFFFFFFFF", spec)
        assert result["name"] == "TANK_STATUS"
        assert result["instance"] == 0
        assert result["relative level"] == 180
        assert result["resolution"] == 240

    def test_generator_status(self, spec):
        # Status byte 0 = 3 (running)
        result = decode("1FFDC", "0300000000C80000", spec)
        assert result["name"] == "GENERATOR_STATUS_1"
        assert result["status"] == 3
        assert result["status definition"] == "running"

    def test_unknown_dgn(self, spec):
        result = decode("FFFFF", "0102030405060708", spec)
        assert result["name"] == "UNKNOWN-FFFFF"
        assert result["dgn"] == "FFFFF"
        assert result["data"] == "0102030405060708"

    def test_thermostat_ambient(self, spec):
        # Instance 1, ambient temp uint16 in bytes 1-2
        # Let's say bytes 1-2 are "E025" → swapped "25E0" = 9696
        # 9696 * 0.03125 - 273 = 303.0 - 273 = 30.0°C
        result = decode("1FF9C", "01E025FFFFFFFFFF", spec)
        assert result["name"] == "THERMOSTAT_AMBIENT_STATUS"
        assert result["instance"] == 1
        assert result["ambient temp"] == 30.0
        assert result["ambient temp F"] == 86.0

    def test_decode_frame_full(self, spec):
        # DC_DIMMER_STATUS_3: arb_id 0x19FEDA9F, instance 17, brightness 100
        result = decode_frame(0x19FEDA9F, "1100C80200FFFFFF", spec)
        assert result["priority"] == 6
        assert result["source"] == 0x9F
        assert result["name"] == "DC_DIMMER_STATUS_3"
        assert result["instance"] == 17
        assert result["operating status (brightness)"] == 100.0

    def test_alias_decode(self, spec):
        """DGNs with aliases should decode using the alias's parameters."""
        # 1FFFE (SET_DATE_TIME_COMMAND) aliases 1FFFF (DATE_TIME_STATUS)
        # It should decode using DATE_TIME_STATUS parameters
        result = decode("1FFFE", "1806080105301E00", spec)
        assert result["name"] == "SET_DATE_TIME_COMMAND"
        assert "year" in result
