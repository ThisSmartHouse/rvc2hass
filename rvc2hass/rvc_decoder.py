"""RV-C protocol decoder.

Decodes raw CAN bus frames into structured data using the RV-C spec YAML.
Ported from CoachProxy's rvc2mqtt.pl.

CAN arbitration ID layout (29-bit extended):
  Bits 28-26: Priority (3 bits)
  Bits 25     : Reserved (always 0 in RV-C)
  Bits 24-8  : DGN - Data Group Number (17 bits)
  Bits 7-0   : Source Address (8 bits)

Data bytes are 8 bytes. Per RV-C spec, multi-byte values are transmitted
least-significant byte first (little-endian), so byte order must be swapped
when extracting multi-byte fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RvcSpec:
    """Loads and provides access to the RV-C DGN spec."""

    def __init__(self, spec_path: Path):
        with open(spec_path) as f:
            raw = yaml.safe_load(f)
        self._api_version = raw.pop("API_VERSION", None)
        self._dgns: dict[str, dict] = raw

    @property
    def api_version(self):
        return self._api_version

    @property
    def dgn_count(self) -> int:
        return len(self._dgns)

    def get_dgn(self, dgn_hex: str) -> dict | None:
        return self._dgns.get(dgn_hex)

    def get_parameters(self, dgn_hex: str) -> list[dict]:
        """Get the full parameter list for a DGN, resolving aliases."""
        dgn = self._dgns.get(dgn_hex)
        if dgn is None:
            return []
        params = []
        # If this DGN has an alias, load the alias's parameters first
        alias = dgn.get("alias")
        if alias and alias in self._dgns:
            alias_dgn = self._dgns[alias]
            params.extend(alias_dgn.get("parameters", []))
        # Then add this DGN's own parameters
        params.extend(dgn.get("parameters", []))
        return params


def parse_can_id(arbitration_id: int) -> tuple[int, str, int]:
    """Parse a 29-bit CAN arbitration ID into RV-C components.

    Args:
        arbitration_id: The 29-bit extended CAN arbitration ID.

    Returns:
        Tuple of (priority, dgn_hex, source_address).
        dgn_hex is a zero-padded 5-character uppercase hex string.
    """
    # Priority is bits 28-26 (top 3 bits of 29-bit ID)
    priority = (arbitration_id >> 26) & 0x07
    # DGN is bits 25-8 (but bit 25 is reserved/0 in RV-C, so effectively 24-8)
    # We extract 17 bits from position 8
    dgn = (arbitration_id >> 8) & 0x1FFFF
    # Source address is bits 7-0
    source = arbitration_id & 0xFF
    dgn_hex = f"{dgn:05X}"
    return priority, dgn_hex, source


def get_bytes(data_hex: str, byte_range: str | int) -> str:
    """Extract bytes from a hex data string, swapping for little-endian.

    Per RV-C spec, multi-byte data is transmitted LSB first. When extracting
    a range of bytes, the order is reversed to get the correct value.

    Args:
        data_hex: Hex string of the 8 data bytes (e.g. "020064C524C52400").
        byte_range: Single byte index (int or "2") or range ("2-3").

    Returns:
        Hex string of the extracted bytes, byte-swapped if multi-byte.
    """
    byte_range = str(byte_range)
    parts = byte_range.split("-")
    start = int(parts[0])
    end = int(parts[1]) if len(parts) > 1 else start

    # Extract the substring
    sub = data_hex[start * 2:(end + 1) * 2]

    # Swap byte order for multi-byte values (little-endian → big-endian)
    if len(sub) > 2:
        # Split into 2-char byte pairs, reverse, rejoin
        pairs = [sub[i:i+2] for i in range(0, len(sub), 2)]
        sub = "".join(reversed(pairs))

    return sub


def get_bits(byte_hex: str, bit_range: str | int) -> str:
    """Extract specific bits from a hex byte.

    Args:
        byte_hex: Hex string of a single byte (e.g. "C5").
        bit_range: Single bit index ("3") or range ("0-1").

    Returns:
        Binary string of the requested bits.
    """
    bit_range = str(bit_range)
    value = int(byte_hex, 16)
    # Convert to 8-bit binary string
    bits = f"{value:08b}"

    parts = bit_range.split("-")
    start_bit = int(parts[0])
    end_bit = int(parts[1]) if len(parts) > 1 else start_bit

    # Perl code: substr($bits, 7 - $end_bit, $end_bit - $start_bit + 1)
    # bits string is MSB-first: bit 7 is index 0, bit 0 is index 7
    begin_idx = 7 - end_bit
    length = end_bit - start_bit + 1
    return bits[begin_idx:begin_idx + length]


def convert_unit(value: int | float, unit: str, dtype: str) -> Any:
    """Convert a raw value based on RV-C Table 5.3 unit conversions.

    Args:
        value: The raw numeric value.
        unit: Unit string from the spec (pct, Deg C, V, A, Hz, sec, bitmap).
        dtype: Data type string (uint8, uint16, uint32).

    Returns:
        Converted value, or "n/a" for sentinel/invalid values.
    """
    unit_lower = unit.lower()

    if unit_lower == "pct":
        if value == 255:
            return "n/a"
        return value / 2

    elif unit_lower == "deg c":
        if dtype == "uint8":
            if value == 255:
                return "n/a"
            return value - 40
        elif dtype == "uint16":
            if value == 65535:
                return "n/a"
            return round(value * 0.03125 - 273, 1)
        return value

    elif unit_lower == "v":
        if dtype == "uint8":
            if value == 255:
                return "n/a"
            return value
        elif dtype == "uint16":
            if value == 65535:
                return "n/a"
            return round(value * 0.05, 1)
        elif dtype == "uint32":
            return value
        return value

    elif unit_lower == "a":
        if dtype == "uint8":
            return value
        elif dtype == "uint16":
            if value == 65535:
                return "n/a"
            return round(value * 0.05 - 1600, 1)
        elif dtype == "uint32":
            if value == 4294967295:
                return "n/a"
            return round(value * 0.001 - 2000000, 2)
        return value

    elif unit_lower == "hz":
        if dtype == "uint8":
            return value
        elif dtype == "uint16":
            return round(value / 128, 1)
        return value

    elif unit_lower == "sec":
        if dtype == "uint8":
            if 240 < value < 251:
                return ((value - 240) + 4) * 60
            return value
        elif dtype == "uint16":
            return value * 2
        return value

    elif unit_lower == "bitmap":
        return f"{value:08b}"

    # Units we don't convert (year, min, rpm, kph, ppm, liter, etc.)
    return value


def decode(dgn_hex: str, data_hex: str, spec: RvcSpec) -> dict[str, Any]:
    """Decode an RV-C CAN frame's data bytes using the spec.

    Args:
        dgn_hex: The DGN as a 5-char hex string (e.g. "1FEDA").
        data_hex: The 8 data bytes as a hex string (e.g. "1200C80200FFFFFF").
        spec: The loaded RV-C spec.

    Returns:
        Dictionary with decoded field names and values. Always includes
        'dgn', 'data', and 'name' keys.
    """
    result: dict[str, Any] = {
        "dgn": dgn_hex,
        "data": data_hex,
        "name": f"UNKNOWN-{dgn_hex}",
    }

    dgn_def = spec.get_dgn(dgn_hex)
    if dgn_def is None:
        return result

    result["name"] = dgn_def["name"]
    parameters = spec.get_parameters(dgn_hex)

    for param in parameters:
        name = param.get("name")
        dtype = param.get("type", "uint")
        unit = param.get("unit")
        values_map = param.get("values")

        # Get the raw bytes
        byte_hex = get_bytes(data_hex, param["byte"])
        value: Any = int(byte_hex, 16)

        # Extract bits if specified
        if "bit" in param:
            bits_str = get_bits(byte_hex, param["bit"])
            value = bits_str
            # Convert from binary to decimal if the type calls for it
            if dtype.startswith("uint") or dtype.startswith("bit") and dtype not in ("bit", "bit1", "bit2", "bit3", "bit4"):
                value = int(bits_str, 2)

        # Apply unit conversion
        if unit and unit.lower() not in ("bitmap",) and not isinstance(value, str):
            value = convert_unit(value, unit, dtype)
        elif unit and unit.lower() == "bitmap" and not isinstance(value, str):
            value = convert_unit(value, unit, dtype)

        if name:
            result[name] = value

        # Provide temperature in °F as well
        if unit and unit.lower() == "deg c" and value != "n/a" and isinstance(value, (int, float)):
            if name:
                result[f"{name} F"] = round((value * 9 / 5) + 32, 1)

        # Decode value definitions
        if values_map and name:
            value_def = values_map.get(value, "undefined")
            # Try string lookup too (for bit fields stored as strings)
            if value_def == "undefined" and isinstance(value, int):
                value_def = values_map.get(str(value), "undefined")
            result[f"{name} definition"] = value_def

    return result


def decode_frame(arbitration_id: int, data_hex: str, spec: RvcSpec) -> dict[str, Any]:
    """Decode a complete CAN frame (arbitration ID + data).

    This is the main entry point for decoding. It parses the CAN ID to
    get the DGN, then decodes the data bytes.

    Args:
        arbitration_id: The 29-bit extended CAN arbitration ID.
        data_hex: The 8 data bytes as a hex string.
        spec: The loaded RV-C spec.

    Returns:
        Dictionary with all decoded fields, plus 'priority', 'source',
        'dgn', 'data', and 'name'.
    """
    priority, dgn_hex, source = parse_can_id(arbitration_id)
    result = decode(dgn_hex, data_hex, spec)
    result["priority"] = priority
    result["source"] = source
    return result
