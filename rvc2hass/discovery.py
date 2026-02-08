"""CAN bus discovery mode.

Listens to the CAN bus for a specified duration and reports:
- Known DGNs seen (with instance counts and frame counts)
- Unknown DGNs (not in the spec)
- Instances in the profile but not seen on the bus
- Instances seen on the bus but not in the profile
"""

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import can

from .config import Profile
from .rvc_decoder import RvcSpec, parse_can_id, decode

log = logging.getLogger(__name__)


class DiscoveryCollector:
    """Collects CAN frame statistics for discovery reporting."""

    def __init__(self, spec: RvcSpec, profile: Profile):
        self.spec = spec
        self.profile = profile
        # dgn_hex → {frame_count, instances: set, sources: set, samples: dict}
        self.known_dgns: dict[str, dict] = defaultdict(
            lambda: {"frame_count": 0, "instances": set(), "sources": set(), "name": ""}
        )
        self.unknown_dgns: dict[str, dict] = defaultdict(
            lambda: {"frame_count": 0, "sources": set(), "samples": {}}
        )

    def process_frame(self, arbitration_id: int, data_hex: str):
        """Process a single CAN frame for discovery statistics."""
        priority, dgn_hex, source = parse_can_id(arbitration_id)
        dgn_def = self.spec.get_dgn(dgn_hex)

        if dgn_def is not None:
            entry = self.known_dgns[dgn_hex]
            entry["frame_count"] += 1
            entry["name"] = dgn_def["name"]
            entry["sources"].add(source)
            # Try to decode instance
            result = decode(dgn_hex, data_hex, self.spec)
            if "instance" in result:
                entry["instances"].add(result["instance"])
        else:
            entry = self.unknown_dgns[dgn_hex]
            entry["frame_count"] += 1
            entry["sources"].add(source)
            # Store one sample per source address
            if source not in entry["samples"]:
                entry["samples"][source] = data_hex

    def _get_profile_instances(self) -> dict[str, set[int]]:
        """Get all instance numbers from the profile, grouped by DGN."""
        instances: dict[str, set[int]] = defaultdict(set)
        # Lights and switches use DC_DIMMER_STATUS_3
        for light in self.profile.lights:
            instances["1FEDA"].add(light.instance)
        for switch in self.profile.switches:
            instances["1FEDA"].add(switch.instance)
        for cover in self.profile.covers:
            instances["1FEDA"].add(cover.extend_instance)
            instances["1FEDA"].add(cover.retract_instance)
        for bs in self.profile.binary_sensors:
            if bs.dgn == "DC_DIMMER_STATUS_3" and bs.instance is not None:
                instances["1FEDA"].add(bs.instance)
        # Sensors by their DGN
        dgn_name_to_hex = {}
        for dgn_hex in list(self.known_dgns.keys()) + list(self.unknown_dgns.keys()):
            dgn_def = self.spec.get_dgn(dgn_hex)
            if dgn_def:
                dgn_name_to_hex[dgn_def["name"]] = dgn_hex
        for sensor in self.profile.sensors:
            dgn_hex = dgn_name_to_hex.get(sensor.dgn)
            if dgn_hex and sensor.instance is not None:
                instances[dgn_hex].add(sensor.instance)
        for bs in self.profile.binary_sensors:
            dgn_hex = dgn_name_to_hex.get(bs.dgn)
            if dgn_hex and bs.instance is not None:
                instances[dgn_hex].add(bs.instance)
        return instances

    def generate_report(self) -> str:
        """Generate a human-readable discovery report."""
        lines = ["", "=== CAN Bus Discovery Report ===", ""]

        # Known DGNs
        lines.append("Known DGNs seen:")
        for dgn_hex in sorted(self.known_dgns, key=lambda k: self.known_dgns[k]["frame_count"], reverse=True):
            entry = self.known_dgns[dgn_hex]
            instances_str = ",".join(str(i) for i in sorted(entry["instances"]))
            lines.append(
                f"  {entry['name']} ({dgn_hex}) - {entry['frame_count']} frames, "
                f"instances: [{instances_str}]"
            )

        # Unknown DGNs
        if self.unknown_dgns:
            lines.append("")
            lines.append("UNKNOWN DGNs seen (not in rvc_spec.yaml):")
            for dgn_hex in sorted(self.unknown_dgns, key=lambda k: self.unknown_dgns[k]["frame_count"], reverse=True):
                entry = self.unknown_dgns[dgn_hex]
                src_str = ", ".join(f"{s:02X}" for s in sorted(entry["sources"]))
                lines.append(
                    f"  DGN {dgn_hex} - {entry['frame_count']} frames, "
                    f"src addresses: [{src_str}], data samples:"
                )
                for src, sample in sorted(entry["samples"].items()):
                    lines.append(f"    {src:02X}: {sample}")

        # Profile gap detection
        profile_instances = self._get_profile_instances()
        bus_instances: dict[str, set[int]] = {}
        for dgn_hex, entry in self.known_dgns.items():
            bus_instances[dgn_hex] = entry["instances"]

        # In profile but not on bus
        missing = []
        for dgn_hex, prof_insts in profile_instances.items():
            bus_insts = bus_instances.get(dgn_hex, set())
            for inst in sorted(prof_insts - bus_insts):
                dgn_def = self.spec.get_dgn(dgn_hex)
                name = dgn_def["name"] if dgn_def else dgn_hex
                missing.append(f"  {name} instance {inst} - no traffic")

        if missing:
            lines.append("")
            lines.append("Instances in profile but NOT seen on bus (possible config errors):")
            lines.extend(missing)

        # On bus but not in profile
        candidates = []
        for dgn_hex, bus_insts in bus_instances.items():
            prof_insts = profile_instances.get(dgn_hex, set())
            for inst in sorted(bus_insts - prof_insts):
                entry = self.known_dgns[dgn_hex]
                candidates.append(
                    f"  {entry['name']} instance {inst} - "
                    f"seen {entry['frame_count']} frames (not in profile)"
                )

        if candidates:
            lines.append("")
            lines.append("Instances seen on bus but NOT in profile (candidates to add):")
            lines.extend(candidates)

        lines.append("")
        return "\n".join(lines)


def run_discovery(profile: Profile, args):
    """Run CAN bus discovery mode.

    Listens to the CAN bus for the specified duration, then prints a report.
    """
    from .can_bus import CANBusReader

    spec_path = args.spec or Path(__file__).parent.parent / "specs" / "rvc_spec.yaml"
    spec = RvcSpec(spec_path)
    collector = DiscoveryCollector(spec, profile)
    reader = CANBusReader(
        interface=profile.can.interface,
        channel=profile.can.channel,
        bitrate=profile.can.bitrate,
    )

    def on_frame(msg: can.Message):
        data_hex = msg.data.hex().upper().ljust(16, '0')[:16]
        collector.process_frame(msg.arbitration_id, data_hex)

    async def scan():
        reader.connect()
        log.info("Scanning for %d seconds...", args.discover_duration)
        try:
            end_time = asyncio.get_event_loop().time() + args.discover_duration
            while asyncio.get_event_loop().time() < end_time:
                loop = asyncio.get_event_loop()
                msg = await loop.run_in_executor(
                    None, lambda: reader._bus.recv(timeout=1.0)
                )
                if msg is not None:
                    on_frame(msg)
        finally:
            reader.disconnect()

        print(collector.generate_report())

    asyncio.run(scan())
