"""
Functional Tests — PTP Synchronization.

Tests PTP time synchronization operations:
- Sync start/stop.
- Status monitoring.
- Accuracy validation against thresholds.

The radar UUT requires valid PTP sync to operate, making
these tests a prerequisite for all radar functional tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.functional
@pytest.mark.xray("RADAR-301")
class TestPTPSync:
    """Tests for PTP synchronization management."""

    def test_ptp_is_synchronized(self, ptp) -> None:
        """Verify PTP sync is established via fixture."""
        assert ptp.is_synced, "PTP should be synchronized after fixture init"

    def test_ptp_sync_status(self, ptp) -> None:
        """Verify PTP sync status reports correct state."""
        result = ptp.get_sync_status()

        assert result.is_success, f"Get sync status failed: {result.error}"
        assert result.data["sync_state"] == "synchronized"
        assert "offset_us" in result.data

    def test_ptp_accuracy_within_threshold(self, ptp, thresholds) -> None:
        """Verify PTP sync accuracy is within configured thresholds."""
        ptp_threshold = thresholds.get("ptp_sync_accuracy", {})
        max_offset_us = ptp_threshold.get("max_offset_us", 1.0)

        result = ptp.validate_accuracy(max_offset_us=max_offset_us)

        assert result.is_success, f"Accuracy validation failed: {result.error}"
        assert result.data["within_threshold"] is True, (
            f"PTP offset {result.data['offset_us']}µs "
            f"exceeds threshold {max_offset_us}µs"
        )

    def test_ptp_offset_is_positive(self, ptp) -> None:
        """Verify PTP offset is reported as a reasonable value."""
        result = ptp.get_sync_status()

        assert result.is_success
        offset = result.data["offset_us"]
        assert offset >= 0, f"PTP offset should be non-negative, got {offset}µs"
        assert offset < 1000, f"PTP offset {offset}µs seems unreasonably large"

