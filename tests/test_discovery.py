"""Tests for CAN bus discovery mode."""

from pathlib import Path

import pytest

from rvc2hass.config import load_profile
from rvc2hass.discovery import DiscoveryCollector
from rvc2hass.rvc_decoder import RvcSpec


SPEC_PATH = Path(__file__).parent.parent / "specs" / "rvc_spec.yaml"
PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "thor_hurricane_35m.yaml"


@pytest.fixture
def spec():
    return RvcSpec(SPEC_PATH)


@pytest.fixture
def profile():
    return load_profile(PROFILE_PATH)


@pytest.fixture
def collector(spec, profile):
    return DiscoveryCollector(spec, profile)


def make_arb_id(dgn_hex: str, source: int = 0x9F, priority: int = 6) -> int:
    """Build a 29-bit CAN arbitration ID from components."""
    dgn = int(dgn_hex, 16)
    return (priority << 26) | (dgn << 8) | source


class TestKnownDGNReport:
    """Discovery correctly identifies known DGNs."""

    def test_counts_frames(self, collector):
        arb_id = make_arb_id("1FEDA")
        for _ in range(10):
            collector.process_frame(arb_id, "1100C80200FFFFFF")
        assert collector.known_dgns["1FEDA"]["frame_count"] == 10

    def test_tracks_instances(self, collector):
        arb_id = make_arb_id("1FEDA")
        # Instance is byte 0 of DC_DIMMER_STATUS_3
        collector.process_frame(arb_id, "1100C80200FFFFFF")  # instance 17
        collector.process_frame(arb_id, "1200C80200FFFFFF")  # instance 18
        collector.process_frame(arb_id, "1100C80200FFFFFF")  # instance 17 again
        assert collector.known_dgns["1FEDA"]["instances"] == {17, 18}

    def test_tracks_name(self, collector):
        arb_id = make_arb_id("1FEDA")
        collector.process_frame(arb_id, "1100C80200FFFFFF")
        assert collector.known_dgns["1FEDA"]["name"] == "DC_DIMMER_STATUS_3"

    def test_tracks_sources(self, collector):
        arb_id_a = make_arb_id("1FEDA", source=0x42)
        arb_id_b = make_arb_id("1FEDA", source=0x44)
        collector.process_frame(arb_id_a, "1100C80200FFFFFF")
        collector.process_frame(arb_id_b, "1200C80200FFFFFF")
        assert collector.known_dgns["1FEDA"]["sources"] == {0x42, 0x44}


class TestUnknownDGNReport:
    """Discovery correctly reports unknown DGNs."""

    def test_unknown_dgn_tracked(self, collector):
        # Use a DGN not in the spec
        arb_id = make_arb_id("00001")
        collector.process_frame(arb_id, "0102030405060708")
        assert "00001" in collector.unknown_dgns
        assert collector.unknown_dgns["00001"]["frame_count"] == 1

    def test_unknown_dgn_samples(self, collector):
        arb_id = make_arb_id("00001", source=0x42)
        collector.process_frame(arb_id, "AABBCCDD00112233")
        assert collector.unknown_dgns["00001"]["samples"][0x42] == "AABBCCDD00112233"


class TestProfileGapDetection:
    """Discovery identifies instances in/not in profile."""

    def test_report_includes_known_dgns(self, collector):
        arb_id = make_arb_id("1FEDA")
        collector.process_frame(arb_id, "1100C80200FFFFFF")
        report = collector.generate_report()
        assert "DC_DIMMER_STATUS_3" in report

    def test_report_includes_unknown_dgns(self, collector):
        arb_id = make_arb_id("00001")
        collector.process_frame(arb_id, "0102030405060708")
        report = collector.generate_report()
        assert "UNKNOWN DGNs" in report
        assert "00001" in report

    def test_candidates_to_add(self, collector):
        """Instances on bus but not in profile are reported as candidates."""
        arb_id = make_arb_id("1FEDA")
        # Instance 99 is not in any profile entity
        collector.process_frame(arb_id, "6300C80200FFFFFF")  # instance 99
        report = collector.generate_report()
        assert "instance 99" in report
        assert "not in profile" in report

    def test_report_structure(self, collector):
        arb_id = make_arb_id("1FEDA")
        collector.process_frame(arb_id, "1100C80200FFFFFF")
        report = collector.generate_report()
        assert "=== CAN Bus Discovery Report ===" in report
        assert "Known DGNs seen:" in report
