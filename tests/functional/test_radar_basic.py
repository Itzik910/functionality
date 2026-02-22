"""
Functional Tests — Radar Basic Operations.

Tests core radar UUT operations using the driver abstraction layer:
- Connection and heartbeat.
- Point cloud / SODA data acquisition.
- State management.
- Statistics monitoring.
- Firmware version verification.

Each test uses the radar_uut fixture from conftest.py which provides
a RadarDriverBase instance (BSR/HRR/Mock depending on configuration).
"""

from __future__ import annotations

import pytest

from src.drivers.radar_driver_base import (
    ConnectStatus,
    HeartbeatData,
    PointCloudFrame,
    StatisticsData,
)


# ---------------------------------------------------------------------------
# Radar Connection Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-101")
class TestRadarConnection:
    """Tests for radar UUT connection and basic connectivity."""

    def test_radar_connection_established(self, radar_uut) -> None:
        """Verify that the radar UUT connection is established via fixture."""
        assert radar_uut.is_connected, "Radar UUT should be connected after fixture init"

    def test_radar_ping(self, radar_uut) -> None:
        """Verify that the radar responds to ping."""
        assert radar_uut.ping() is True, "Radar should respond to ping"

    def test_radar_fw_version(self, radar_uut) -> None:
        """Verify that firmware version is reported."""
        fw = radar_uut.fw_version
        assert fw, "Firmware version should not be empty"
        assert isinstance(fw, str)


# ---------------------------------------------------------------------------
# Radar Heartbeat Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-104")
class TestRadarHeartbeat:
    """Tests for radar heartbeat monitoring."""

    def test_heartbeat_received(self, radar_uut) -> None:
        """Verify that a heartbeat message is received."""
        hb = radar_uut.get_heartbeat(timeout=5)
        assert hb is not None, "Should receive a heartbeat"
        assert isinstance(hb, HeartbeatData)

    def test_heartbeat_has_valid_data(self, radar_uut) -> None:
        """Verify heartbeat contains expected data fields."""
        hb = radar_uut.get_heartbeat(timeout=5)
        assert hb is not None
        assert hb.beat_id > 0
        assert hb.status == "OK"
        assert hb.sensor_type != ""

    def test_heartbeat_reports_temperatures(self, radar_uut) -> None:
        """Verify heartbeat includes temperature readings."""
        hb = radar_uut.get_heartbeat(timeout=5)
        assert hb is not None
        assert len(hb.temperatures) > 0
        for temp_name, temp_val in hb.temperatures.items():
            assert 0 < temp_val < 100, f"Temperature {temp_name}={temp_val}°C out of range"


# ---------------------------------------------------------------------------
# Radar Data Acquisition Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-102")
class TestRadarDataAcquisition:
    """Tests for radar point cloud / SODA frame acquisition."""

    def test_point_cloud_received(self, radar_uut) -> None:
        """Verify that a point cloud frame is received."""
        pc = radar_uut.get_point_cloud(timeout=5)
        assert pc is not None, "Should receive a point cloud frame"
        assert isinstance(pc, PointCloudFrame)

    def test_point_cloud_has_detections(self, radar_uut) -> None:
        """Verify that point cloud contains valid detections."""
        pc = radar_uut.get_point_cloud(timeout=5)
        assert pc is not None
        assert pc.valid_detections > 0
        assert len(pc.detections) == pc.valid_detections

    def test_point_cloud_detection_fields(self, radar_uut) -> None:
        """Verify that detections have required coordinate fields."""
        pc = radar_uut.get_point_cloud(timeout=5)
        assert pc is not None
        assert len(pc.detections) > 0
        det = pc.detections[0]
        assert hasattr(det, "distance")
        assert hasattr(det, "azimuth")
        assert hasattr(det, "velocity")
        assert hasattr(det, "rcs")

    def test_point_cloud_cycle_counter(self, radar_uut) -> None:
        """Verify that cycle counter increments across frames."""
        pc1 = radar_uut.get_point_cloud(timeout=5)
        pc2 = radar_uut.get_point_cloud(timeout=5)
        assert pc1 is not None and pc2 is not None
        assert pc2.cycle_count > pc1.cycle_count


# ---------------------------------------------------------------------------
# Radar State Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-105")
class TestRadarStateManagement:
    """Tests for radar state transitions."""

    def test_set_state_scanning(self, radar_uut) -> None:
        """Verify radar can be moved to SCANNING state."""
        assert radar_uut.set_state("SCANNING") is True
        assert radar_uut.state == "SCANNING"

    def test_set_state_standby(self, radar_uut) -> None:
        """Verify radar can be moved to STANDBY state."""
        assert radar_uut.set_state("STANDBY") is True
        assert radar_uut.state == "STANDBY"


# ---------------------------------------------------------------------------
# Radar Statistics Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-103")
class TestRadarStatistics:
    """Tests for radar runtime statistics monitoring."""

    def test_statistics_fps(self, radar_uut) -> None:
        """Verify FPS statistics are reported."""
        stats = radar_uut.get_statistics()
        assert isinstance(stats, StatisticsData)
        assert stats.fps_mean > 0, "FPS mean should be positive"

    def test_statistics_latency(self, radar_uut) -> None:
        """Verify latency statistics are reported."""
        stats = radar_uut.get_statistics()
        assert stats.latency_mean_ms > 0, "Latency should be positive"
