"""
Functional Tests — Radar Basic Operations.

Tests core radar UUT operations using atomic actions:
- Initialization and connection.
- Data transmission and reception.
- Status monitoring.
- Self-test execution.

Each test demonstrates the atomic action pattern and uses
Pytest fixtures from conftest.py for hardware orchestration.
"""

from __future__ import annotations

import pytest

from src.actions.base import ActionStatus


# ---------------------------------------------------------------------------
# Radar Initialization Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-101")
class TestRadarInitialization:
    """Tests for radar UUT initialization and connection management."""

    def test_radar_connection_established(self, radar_uut) -> None:
        """Verify that the radar UUT connection is established via fixture."""
        assert radar_uut.is_connected, "Radar UUT should be connected after fixture init"

    def test_radar_status_after_init(self, radar_uut) -> None:
        """Verify radar reports operational status after initialization."""
        result = radar_uut.get_status()

        assert result.is_success, f"Get status failed: {result.error}"
        assert result.data["operational"] is True
        assert "firmware_version" in result.data


# ---------------------------------------------------------------------------
# Radar Data Transmission Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-102")
class TestRadarDataTransmission:
    """Tests for radar data transmission and reception."""

    def test_transmit_data(self, radar_uut) -> None:
        """Verify that data can be transmitted to the radar UUT."""
        payload = b"\x01\x02\x03\x04\x05"
        result = radar_uut.transmit_data(payload=payload)

        assert result.is_success, f"Transmit failed: {result.error}"
        assert result.data["bytes_sent"] == len(payload)

    def test_receive_data(self, radar_uut) -> None:
        """Verify that data can be received from the radar UUT."""
        result = radar_uut.receive_data(timeout_sec=5.0)

        assert result.is_success, f"Receive failed: {result.error}"
        assert result.data["bytes_received"] > 0
        assert "data" in result.data

    def test_transmit_empty_payload_rejected(self, radar_uut) -> None:
        """Verify that transmitting with invalid payload is properly handled."""
        result = radar_uut.transmit_data(payload="not_bytes")

        assert result.is_failure, "Should fail with non-bytes payload"
        assert result.status == ActionStatus.ERROR

    def test_transmit_reports_timing(self, radar_uut) -> None:
        """Verify that transmission reports execution timing."""
        payload = b"\xAA\xBB\xCC"
        result = radar_uut.transmit_data(payload=payload)

        assert result.duration_ms >= 0
        assert result.duration_ms < 10000  # Should complete within 10s


# ---------------------------------------------------------------------------
# Radar Self-Test
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.xray("RADAR-103")
class TestRadarSelfTest:
    """Tests for the radar built-in self-test."""

    def test_self_test_passes(self, radar_uut) -> None:
        """Verify that the radar self-test reports all subsystems as operational."""
        result = radar_uut.run_self_test()

        assert result.is_success, f"Self-test failed: {result.error}"
        assert result.data["self_test_passed"] is True
        assert result.data["tests_failed"] == 0

    def test_self_test_reports_all_tests(self, radar_uut) -> None:
        """Verify that the self-test reports the number of tests run."""
        result = radar_uut.run_self_test()

        assert result.data["tests_run"] > 0
        assert result.data["tests_passed"] == result.data["tests_run"]

