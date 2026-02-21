"""
Health Check Utility Module.

Provides pre-flight health checks for test benches before allocation.
In the initial PoC, these are mock implementations. In production,
they would perform actual network checks (ping, PSU communication, etc.).

Design Reference: "Before granting a Lock on a resource, the RM must perform
a basic health check (e.g., ping the UUT, verify PSU communication)."
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class HealthCheckResult:
    """
    Result of a health check on a test bench.

    Attributes:
        bench_id: The bench that was checked.
        healthy: Whether the bench passed all checks.
        checks: Individual check results.
        message: Summary message.
    """

    bench_id: str
    healthy: bool = True
    checks: Dict[str, bool] = field(default_factory=dict)
    message: str = "All checks passed."
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed_checks(self) -> List[str]:
        """Return list of check names that failed."""
        return [name for name, passed in self.checks.items() if not passed]


class HealthChecker:
    """
    Performs pre-flight health checks on test benches.

    This is the mock/PoC version. Each check simulates the verification
    and returns configurable results. In production, real network I/O
    would replace the mock logic.

    Usage::

        checker = HealthChecker()
        result = checker.check_bench(bench_config)
        if result.healthy:
            # Bench is ready for allocation
            ...
        else:
            # Mark bench offline
            ...
    """

    def __init__(
        self,
        ping_timeout_sec: int = 5,
        psu_verify_timeout_sec: int = 10,
        retry_count: int = 2,
        mock_mode: bool = True,
    ) -> None:
        """
        Initialize the health checker.

        Args:
            ping_timeout_sec: Timeout for ping checks.
            psu_verify_timeout_sec: Timeout for PSU verification.
            retry_count: Number of retries for failed checks.
            mock_mode: If True, simulate all checks (for PoC/testing).
        """
        self.ping_timeout_sec = ping_timeout_sec
        self.psu_verify_timeout_sec = psu_verify_timeout_sec
        self.retry_count = retry_count
        self.mock_mode = mock_mode

        # Mock overrides — set specific bench IDs to fail for testing
        self._mock_failures: Dict[str, List[str]] = {}

        logger.info(
            f"HealthChecker initialized — mock_mode={mock_mode}, "
            f"ping_timeout={ping_timeout_sec}s, retries={retry_count}"
        )

    def set_mock_failure(self, bench_id: str, failing_checks: List[str]) -> None:
        """
        Configure a bench to fail specific checks (mock mode only).

        Args:
            bench_id: Bench ID to configure.
            failing_checks: List of check names to fail (e.g., ["ping_uut", "verify_psu"]).
        """
        self._mock_failures[bench_id] = failing_checks
        logger.debug(f"Mock failure set for {bench_id}: {failing_checks}")

    def clear_mock_failures(self) -> None:
        """Clear all mock failure configurations."""
        self._mock_failures.clear()

    def check_bench(self, bench_config: Dict[str, Any]) -> HealthCheckResult:
        """
        Perform a full health check on a test bench.

        Runs all checks: UUT ping, PSU verify, PTP connectivity.

        Args:
            bench_config: Bench configuration dictionary with connection details.

        Returns:
            HealthCheckResult with overall status and individual check results.
        """
        bench_id = bench_config.get("bench_id", "UNKNOWN")
        connection = bench_config.get("connection", {})

        logger.info(f"Starting health check for bench: {bench_id}")

        result = HealthCheckResult(bench_id=bench_id)
        checks_to_run = [
            ("ping_uut", self._check_ping_uut, connection),
            ("verify_psu", self._check_verify_psu, connection),
            ("ptp_connectivity", self._check_ptp_connectivity, connection),
        ]

        for check_name, check_fn, conn_data in checks_to_run:
            passed = self._run_check_with_retry(
                check_name, check_fn, conn_data, bench_id
            )
            result.checks[check_name] = passed
            if not passed:
                result.healthy = False

        # Build summary message
        if result.healthy:
            result.message = f"Bench {bench_id}: All {len(result.checks)} checks passed."
            logger.info(result.message)
        else:
            failed = result.failed_checks
            result.message = (
                f"Bench {bench_id}: {len(failed)} check(s) failed — {', '.join(failed)}"
            )
            logger.warning(result.message)

        result.details = {
            "bench_id": bench_id,
            "connection": connection,
            "checks_run": len(result.checks),
            "checks_passed": sum(1 for v in result.checks.values() if v),
        }

        return result

    def _run_check_with_retry(
        self,
        check_name: str,
        check_fn: Any,
        connection: Dict[str, Any],
        bench_id: str,
    ) -> bool:
        """Run a single check with retries."""
        for attempt in range(1, self.retry_count + 1):
            try:
                passed = check_fn(connection, bench_id)
                if passed:
                    return True
                logger.debug(
                    f"Check '{check_name}' failed for {bench_id} "
                    f"(attempt {attempt}/{self.retry_count})"
                )
            except Exception as e:
                logger.error(
                    f"Check '{check_name}' raised exception for {bench_id}: {e} "
                    f"(attempt {attempt}/{self.retry_count})"
                )
        return False

    def _check_ping_uut(
        self, connection: Dict[str, Any], bench_id: str
    ) -> bool:
        """
        Check UUT reachability via ping.

        In mock mode: returns True unless bench is configured to fail.
        In production: performs actual ICMP ping.
        """
        uut_ip = connection.get("uut_ip", "")

        if self.mock_mode:
            mock_fails = self._mock_failures.get(bench_id, [])
            if "ping_uut" in mock_fails:
                logger.debug(f"[MOCK] Ping to {uut_ip} FAILED (configured mock failure)")
                return False
            logger.debug(f"[MOCK] Ping to {uut_ip} OK")
            return True

        # Production implementation (not used in PoC)
        try:
            param = "-n" if sys.platform == "win32" else "-c"
            result = subprocess.run(
                ["ping", param, "1", "-w", str(self.ping_timeout_sec * 1000), uut_ip],
                capture_output=True,
                timeout=self.ping_timeout_sec + 5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Ping to {uut_ip} failed: {e}")
            return False

    def _check_verify_psu(
        self, connection: Dict[str, Any], bench_id: str
    ) -> bool:
        """
        Verify PSU communication.

        In mock mode: returns True unless bench is configured to fail.
        In production: opens a connection to the PSU and queries status.
        """
        psu_ip = connection.get("psu_ip", "")

        if self.mock_mode:
            mock_fails = self._mock_failures.get(bench_id, [])
            if "verify_psu" in mock_fails:
                logger.debug(f"[MOCK] PSU verify at {psu_ip} FAILED")
                return False
            logger.debug(f"[MOCK] PSU at {psu_ip} verified OK")
            return True

        # Production: would connect to PSU and query identity/status
        logger.warning("Production PSU check not implemented — passing by default")
        return True

    def _check_ptp_connectivity(
        self, connection: Dict[str, Any], bench_id: str
    ) -> bool:
        """
        Check PTP time server connectivity.

        In mock mode: returns True unless bench is configured to fail.
        In production: verifies PTP service is reachable and responding.
        """
        ptp_ip = connection.get("ptp_ip", "")

        if self.mock_mode:
            mock_fails = self._mock_failures.get(bench_id, [])
            if "ptp_connectivity" in mock_fails:
                logger.debug(f"[MOCK] PTP at {ptp_ip} FAILED")
                return False
            logger.debug(f"[MOCK] PTP at {ptp_ip} OK")
            return True

        # Production: would verify PTP service
        logger.warning("Production PTP check not implemented — passing by default")
        return True

