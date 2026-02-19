"""
PTP (Precision Time Protocol) Atomic Actions.

Encapsulates atomic operations for PTP time synchronization:
- Starting/stopping PTP synchronization.
- Monitoring sync status and offset.
- Validating sync accuracy against thresholds.

Design Reference: Section 1 — "PTP Time Synchronization: Managed by the Host;
the radar requires valid PTP sync to operate."
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from src.actions.base import ActionResult, AtomicAction


class PTPActions:
    """
    Collection of atomic actions for PTP synchronization management.

    Provides a high-level API for PTP control. The radar UUT requires
    valid PTP sync before it can operate, making this a prerequisite
    for all functional test scenarios.

    Usage::

        ptp = PTPActions(master_ip="192.168.1.1", domain=0)
        result = ptp.start_sync()
        assert result.is_success
    """

    def __init__(
        self,
        master_ip: str = "192.168.1.1",
        domain: int = 0,
        sync_timeout_sec: int = 30,
    ) -> None:
        """
        Initialize PTP actions interface.

        Args:
            master_ip: PTP master clock IP address.
            domain: PTP domain number.
            sync_timeout_sec: Timeout for sync acquisition.
        """
        self.master_ip = master_ip
        self.domain = domain
        self.sync_timeout_sec = sync_timeout_sec
        self._synced = False
        logger.info(
            f"PTPActions initialized — master={master_ip}, domain={domain}"
        )

    def start_sync(self, **kwargs: Any) -> ActionResult:
        """Start PTP synchronization with the master clock."""
        action = _StartSyncAction(
            master_ip=self.master_ip,
            domain=self.domain,
            timeout_sec=self.sync_timeout_sec,
        )
        result = action.run(**kwargs)
        if result.is_success:
            self._synced = True
        return result

    def stop_sync(self, **kwargs: Any) -> ActionResult:
        """Stop PTP synchronization."""
        action = _StopSyncAction(master_ip=self.master_ip)
        result = action.run(**kwargs)
        if result.is_success:
            self._synced = False
        return result

    def get_sync_status(self, **kwargs: Any) -> ActionResult:
        """Get current PTP sync status and offset."""
        action = _GetSyncStatusAction(master_ip=self.master_ip)
        return action.run(**kwargs)

    def validate_accuracy(
        self, max_offset_us: float = 1.0, **kwargs: Any
    ) -> ActionResult:
        """
        Validate that PTP sync accuracy is within the required threshold.

        Args:
            max_offset_us: Maximum acceptable offset in microseconds.
        """
        action = _ValidateAccuracyAction(master_ip=self.master_ip)
        return action.run(max_offset_us=max_offset_us, **kwargs)

    @property
    def is_synced(self) -> bool:
        """Check if PTP synchronization is currently active."""
        return self._synced


# ---------------------------------------------------------------------------
# Internal Atomic Action Implementations
# ---------------------------------------------------------------------------


class _StartSyncAction(AtomicAction):
    """Atomic action: Start PTP synchronization."""

    def __init__(self, master_ip: str, domain: int, timeout_sec: int) -> None:
        super().__init__(name="ptp_start_sync", timeout_sec=float(timeout_sec))
        self.master_ip = master_ip
        self.domain = domain

    def _validate(self, **kwargs: Any) -> None:
        if not self.master_ip:
            raise ValueError("PTP master IP address is required")

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        logger.info(
            f"Starting PTP sync — master={self.master_ip}, domain={self.domain}"
        )
        # TODO: Replace with actual PTP daemon control
        # e.g., subprocess.run(["ptp4l", "-i", "eth0", "-m"])
        return {
            "sync_state": "synchronized",
            "master_ip": self.master_ip,
            "domain": self.domain,
            "offset_us": 0.12,
        }


class _StopSyncAction(AtomicAction):
    """Atomic action: Stop PTP synchronization."""

    def __init__(self, master_ip: str) -> None:
        super().__init__(name="ptp_stop_sync", timeout_sec=5.0)
        self.master_ip = master_ip

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        logger.info(f"Stopping PTP sync for master {self.master_ip}")
        # TODO: Replace with actual PTP daemon stop
        return {"sync_state": "stopped", "master_ip": self.master_ip}


class _GetSyncStatusAction(AtomicAction):
    """Atomic action: Get current PTP sync status."""

    def __init__(self, master_ip: str) -> None:
        super().__init__(name="ptp_get_status", timeout_sec=5.0)
        self.master_ip = master_ip

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        logger.info(f"Querying PTP sync status for master {self.master_ip}")
        # TODO: Replace with actual PTP status query
        return {
            "sync_state": "synchronized",
            "master_ip": self.master_ip,
            "offset_us": 0.15,
            "path_delay_us": 0.08,
            "clock_class": 6,
        }


class _ValidateAccuracyAction(AtomicAction):
    """Atomic action: Validate PTP sync accuracy against threshold."""

    def __init__(self, master_ip: str) -> None:
        super().__init__(name="ptp_validate_accuracy", timeout_sec=5.0)
        self.master_ip = master_ip

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        max_offset_us = kwargs.get("max_offset_us", 1.0)
        # TODO: Replace with actual PTP offset measurement
        current_offset_us = 0.15  # Mock value

        is_within_threshold = abs(current_offset_us) <= max_offset_us
        logger.info(
            f"PTP accuracy check: offset={current_offset_us}µs, "
            f"threshold={max_offset_us}µs, pass={is_within_threshold}"
        )
        return {
            "offset_us": current_offset_us,
            "max_offset_us": max_offset_us,
            "within_threshold": is_within_threshold,
        }

