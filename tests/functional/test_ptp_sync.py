"""
Functional Tests — PTP Synchronization.

Tests PTP (ptp4l) time synchronization operations:
- Sync start/stop.
- Status monitoring.
- Accuracy validation.

The radar UUT requires valid PTP sync to operate, making
these tests a prerequisite for all radar functional tests.

Uses the ptp_sync fixture from conftest.py which provides
a PTPDriver instance (real ptp4l or simulation).
"""

from __future__ import annotations

import pytest

from src.drivers.ptp_driver import PTPStatus


@pytest.mark.functional
@pytest.mark.xray("RADAR-301")
class TestPTPSync:
    """Tests for PTP synchronization management."""

    def test_ptp_is_running(self, ptp_sync) -> None:
        """Verify PTP process is running via fixture."""
        assert ptp_sync.is_running, "PTP should be running after fixture init"

    def test_ptp_is_synchronized(self, ptp_sync) -> None:
        """Verify PTP sync is established via fixture."""
        assert ptp_sync.is_synced, "PTP should be synchronized after fixture init"

    def test_ptp_status(self, ptp_sync) -> None:
        """Verify PTP status reports correct state."""
        status = ptp_sync.get_status()
        assert isinstance(status, PTPStatus)
        assert status.running is True
        assert status.synced is True
        assert status.state == "SLAVE"

    def test_ptp_offset(self, ptp_sync) -> None:
        """Verify PTP offset is within reasonable bounds."""
        status = ptp_sync.get_status()
        assert status.offset_ns >= 0, f"PTP offset should be non-negative, got {status.offset_ns}ns"
        assert status.offset_ns < 1_000_000, f"PTP offset {status.offset_ns}ns seems unreasonably large"

    def test_ptp_delay(self, ptp_sync) -> None:
        """Verify PTP delay is reported."""
        status = ptp_sync.get_status()
        assert status.delay_ns >= 0
