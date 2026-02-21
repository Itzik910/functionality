"""
Resource Manager Module.

Implements the ResourceManager class that bridges software execution (GitLab CI)
with physical hardware state (Radar Test Benches). Handles:
- Hardware-aware allocation: maps hardware_type to physical benches.
- Pre-flight health checks before granting resource locks.
- Concurrency & locking: ensures no two jobs occupy the same bench.
- Resource metadata for test reports.

Design Reference: Section 6 — "Resource Manager & CI/CD Orchestration"
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from src.resource_manager.health_check import HealthChecker, HealthCheckResult


class BenchState(Enum):
    """Possible states for a test bench."""

    AVAILABLE = "available"
    BUSY = "busy"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


@dataclass
class ResourceMetadata:
    """
    Metadata about an allocated resource, attached to test reports.

    Attributes:
        bench_id: Unique identifier of the allocated bench.
        hardware_type: Type of hardware (e.g., "radar_x_band").
        uut_ip: UUT IP address.
        psu_ip: PSU IP address.
        ptp_ip: PTP IP address.
        location: Physical location of the bench.
        allocated_at: Timestamp of allocation.
        health_check_result: Result of the pre-flight health check.
    """

    bench_id: str = ""
    hardware_type: str = ""
    uut_ip: str = ""
    psu_ip: str = ""
    ptp_ip: str = ""
    psu_port: int = 0
    uut_port: int = 0
    location: str = ""
    allocated_at: float = 0.0
    health_check_result: Optional[HealthCheckResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dictionary for report attachment."""
        return {
            "bench_id": self.bench_id,
            "hardware_type": self.hardware_type,
            "uut_ip": self.uut_ip,
            "psu_ip": self.psu_ip,
            "ptp_ip": self.ptp_ip,
            "psu_port": self.psu_port,
            "uut_port": self.uut_port,
            "location": self.location,
            "allocated_at": self.allocated_at,
            "health_check_passed": (
                self.health_check_result.healthy
                if self.health_check_result
                else None
            ),
        }


class ResourceAllocationError(Exception):
    """Raised when a resource cannot be allocated."""

    pass


class ResourceManager:
    """
    Manages test bench allocation, health checks, and concurrency.

    The ResourceManager maintains an inventory of physical test benches,
    handles locking to prevent concurrent usage, and performs health
    checks before granting access.

    Usage::

        rm = ResourceManager(benches_config=config_data)

        # Request a bench
        metadata = rm.request_resource("radar_x_band")
        print(f"Allocated: {metadata.bench_id} at {metadata.uut_ip}")

        # Run tests...

        # Release the bench
        rm.release_resource(metadata.bench_id)

    Thread Safety:
        All allocation/release operations are thread-safe via a threading lock.
    """

    def __init__(
        self,
        benches_config: Optional[Dict[str, Any]] = None,
        max_concurrent_jobs: int = 4,
        health_checker: Optional[HealthChecker] = None,
    ) -> None:
        """
        Initialize the Resource Manager.

        Args:
            benches_config: Parsed test_benches.yaml configuration.
            max_concurrent_jobs: Maximum number of concurrent allocations.
            health_checker: HealthChecker instance (created if not provided).
        """
        self._lock = threading.Lock()
        self._max_concurrent_jobs = max_concurrent_jobs

        # Parse bench inventory
        self._benches: Dict[str, Dict[str, Any]] = {}
        self._bench_states: Dict[str, BenchState] = {}
        self._allocations: Dict[str, str] = {}  # bench_id -> job_id

        if benches_config:
            self._load_benches(benches_config)

        # Health checker
        health_config = (benches_config or {}).get("health_check", {})
        self._health_checker = health_checker or HealthChecker(
            ping_timeout_sec=health_config.get("ping_timeout_sec", 5),
            psu_verify_timeout_sec=health_config.get("psu_verify_timeout_sec", 10),
            retry_count=health_config.get("retry_count", 2),
            mock_mode=True,  # PoC always uses mock mode
        )
        self._mark_offline_on_failure = health_config.get("mark_offline_on_failure", True)

        logger.info(
            f"ResourceManager initialized — {len(self._benches)} benches, "
            f"max_concurrent={self._max_concurrent_jobs}"
        )

    def _load_benches(self, config: Dict[str, Any]) -> None:
        """Load bench definitions from configuration."""
        benches_list = config.get("benches", [])

        for bench in benches_list:
            bench_id = bench.get("bench_id", "")
            if not bench_id:
                logger.warning("Skipping bench with no bench_id")
                continue

            self._benches[bench_id] = bench

            state_str = bench.get("state", "available").lower()
            try:
                self._bench_states[bench_id] = BenchState(state_str)
            except ValueError:
                logger.warning(
                    f"Unknown state '{state_str}' for bench {bench_id}, "
                    f"defaulting to OFFLINE"
                )
                self._bench_states[bench_id] = BenchState.OFFLINE

        logger.info(
            f"Loaded {len(self._benches)} benches: "
            f"{self._count_by_state()}"
        )

    def _count_by_state(self) -> Dict[str, int]:
        """Count benches by state."""
        counts: Dict[str, int] = {}
        for state in self._bench_states.values():
            counts[state.value] = counts.get(state.value, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_resource(
        self,
        hardware_type: str,
        job_id: str = "",
        skip_health_check: bool = False,
    ) -> ResourceMetadata:
        """
        Request a test bench of the specified hardware type.

        Finds an available bench matching the hardware type, performs
        a health check, and locks it for exclusive use.

        Args:
            hardware_type: Required hardware type (e.g., "radar_x_band").
            job_id: Optional job identifier for tracking.
            skip_health_check: Skip the pre-flight health check.

        Returns:
            ResourceMetadata with bench details for test reports.

        Raises:
            ResourceAllocationError: If no bench is available or all fail health checks.
        """
        with self._lock:
            logger.info(
                f"Resource request: hardware_type={hardware_type}, job_id={job_id}"
            )

            # Check concurrent job limit
            current_allocations = len(self._allocations)
            if current_allocations >= self._max_concurrent_jobs:
                raise ResourceAllocationError(
                    f"Maximum concurrent jobs reached ({self._max_concurrent_jobs}). "
                    f"Currently {current_allocations} benches allocated."
                )

            # Find matching available benches
            candidates = self._find_candidates(hardware_type)

            if not candidates:
                available_types = self._get_available_types()
                raise ResourceAllocationError(
                    f"No available bench for hardware_type='{hardware_type}'. "
                    f"Available types: {available_types}"
                )

            # Try to allocate, running health checks
            for bench_id in candidates:
                bench_config = self._benches[bench_id]

                if not skip_health_check:
                    health_result = self._health_checker.check_bench(bench_config)

                    if not health_result.healthy:
                        logger.warning(
                            f"Bench {bench_id} failed health check: "
                            f"{health_result.message}"
                        )
                        if self._mark_offline_on_failure:
                            self._bench_states[bench_id] = BenchState.OFFLINE
                            logger.info(f"Bench {bench_id} marked OFFLINE")
                        continue
                else:
                    health_result = None

                # Allocate the bench
                self._bench_states[bench_id] = BenchState.BUSY
                effective_job_id = job_id or f"auto-{bench_id}-{int(time.time())}"
                self._allocations[bench_id] = effective_job_id

                connection = bench_config.get("connection", {})
                metadata = ResourceMetadata(
                    bench_id=bench_id,
                    hardware_type=hardware_type,
                    uut_ip=connection.get("uut_ip", ""),
                    psu_ip=connection.get("psu_ip", ""),
                    ptp_ip=connection.get("ptp_ip", ""),
                    psu_port=connection.get("psu_port", 0),
                    uut_port=connection.get("uut_port", 0),
                    location=bench_config.get("location", ""),
                    allocated_at=time.time(),
                    health_check_result=health_result,
                )

                logger.info(
                    f"Bench {bench_id} allocated to job '{effective_job_id}' "
                    f"(UUT: {metadata.uut_ip})"
                )
                return metadata

            # All candidates failed health checks
            raise ResourceAllocationError(
                f"All {len(candidates)} candidate bench(es) for "
                f"hardware_type='{hardware_type}' failed health checks."
            )

    def release_resource(self, bench_id: str) -> bool:
        """
        Release a previously allocated test bench.

        Sets the bench state back to AVAILABLE and removes the allocation.

        Args:
            bench_id: The bench ID to release.

        Returns:
            True if the bench was released, False if it wasn't allocated.
        """
        with self._lock:
            if bench_id not in self._allocations:
                logger.warning(f"Bench {bench_id} is not currently allocated")
                return False

            job_id = self._allocations.pop(bench_id)
            self._bench_states[bench_id] = BenchState.AVAILABLE

            logger.info(
                f"Bench {bench_id} released from job '{job_id}' — now AVAILABLE"
            )
            return True

    def get_bench_status(self, bench_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current status of a specific bench.

        Args:
            bench_id: The bench ID to query.

        Returns:
            Dictionary with bench status details, or None if not found.
        """
        if bench_id not in self._benches:
            return None

        bench = self._benches[bench_id]
        state = self._bench_states.get(bench_id, BenchState.OFFLINE)
        job_id = self._allocations.get(bench_id)

        return {
            "bench_id": bench_id,
            "hardware_type": bench.get("hardware_type", ""),
            "state": state.value,
            "allocated_to": job_id,
            "location": bench.get("location", ""),
            "connection": bench.get("connection", {}),
        }

    def get_all_bench_statuses(self) -> List[Dict[str, Any]]:
        """Get status of all benches."""
        statuses = []
        for bench_id in self._benches:
            status = self.get_bench_status(bench_id)
            if status:
                statuses.append(status)
        return statuses

    def get_available_count(self, hardware_type: Optional[str] = None) -> int:
        """
        Get the number of available benches, optionally filtered by type.

        Args:
            hardware_type: Filter by hardware type (None for all types).

        Returns:
            Count of available benches.
        """
        count = 0
        for bench_id, state in self._bench_states.items():
            if state != BenchState.AVAILABLE:
                continue
            if hardware_type:
                bench = self._benches.get(bench_id, {})
                if bench.get("hardware_type") != hardware_type:
                    continue
            count += 1
        return count

    def set_bench_state(self, bench_id: str, state: BenchState) -> bool:
        """
        Manually set the state of a bench (e.g., for maintenance).

        Args:
            bench_id: The bench ID.
            state: New state to set.

        Returns:
            True if the state was set, False if bench not found.
        """
        with self._lock:
            if bench_id not in self._benches:
                logger.warning(f"Bench {bench_id} not found")
                return False

            old_state = self._bench_states.get(bench_id, BenchState.OFFLINE)
            self._bench_states[bench_id] = state

            # Clean up allocation if moving away from BUSY
            if old_state == BenchState.BUSY and state != BenchState.BUSY:
                self._allocations.pop(bench_id, None)

            logger.info(
                f"Bench {bench_id} state changed: "
                f"{old_state.value} -> {state.value}"
            )
            return True

    @property
    def max_concurrent_jobs(self) -> int:
        """Return the maximum concurrent jobs setting."""
        return self._max_concurrent_jobs

    @property
    def current_allocations(self) -> int:
        """Return the number of currently allocated benches."""
        return len(self._allocations)

    @property
    def health_checker(self) -> HealthChecker:
        """Return the health checker instance."""
        return self._health_checker

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _find_candidates(self, hardware_type: str) -> List[str]:
        """Find available benches matching the given hardware type."""
        candidates = []
        for bench_id, bench in self._benches.items():
            if bench.get("hardware_type") != hardware_type:
                continue
            if self._bench_states.get(bench_id) != BenchState.AVAILABLE:
                continue
            candidates.append(bench_id)

        logger.debug(
            f"Found {len(candidates)} candidate(s) for "
            f"hardware_type='{hardware_type}': {candidates}"
        )
        return candidates

    def _get_available_types(self) -> List[str]:
        """Get list of hardware types that have available benches."""
        types = set()
        for bench_id, bench in self._benches.items():
            if self._bench_states.get(bench_id) == BenchState.AVAILABLE:
                types.add(bench.get("hardware_type", "unknown"))
        return sorted(types)

