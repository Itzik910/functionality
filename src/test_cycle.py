"""
Test Cycle Manager — orchestrates nightly, regression, and milestone cycles.

Defines the three test cycle types:
- Nightly: Runs every night, basic tests, latest nightly firmware
- Regression: Runs weekly, extensive tests, weekly firmware
- Milestone: On-demand, all tests, specific release firmware

Each cycle type has associated Jira Test Sets per project:
- DR64 (VW): VW Nightly Set, VW Regression Set, VW Milestone Set
- MBAG: MBAG Nightly Set, MBAG Regression Set, MBAG Milestone Set
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class CycleType(Enum):
    """Test cycle types."""
    NIGHTLY = "nightly"
    REGRESSION = "regression"
    MILESTONE = "milestone"


class EnvironmentType(Enum):
    """Test environment types."""
    COFFIN = "coffin"   # 4 radars, interference management needed
    OVEN = "oven"       # 1 radar, thermal tests


@dataclass
class TestCycleConfig:
    """Configuration for a test cycle execution."""
    cycle_type: CycleType
    project: str  # "DR64" or "MBAG"
    radar_type: str  # "BSR32", "BSRC", "HRR"
    environment: EnvironmentType = EnvironmentType.COFFIN
    fw_version: Optional[str] = None  # Specific version for milestone
    test_set_key: str = ""  # Jira Test Set key (e.g., "RADAR-13523")
    markers: List[str] = field(default_factory=list)  # Pytest markers to run


# Mapping: (project, cycle_type) -> test set info
TEST_SET_REGISTRY: Dict[str, Dict[str, str]] = {
    "DR64": {
        "nightly": "VW Nightly Set",
        "regression": "VW Regression Set",
        "milestone": "VW Milestone Set",
    },
    "MBAG": {
        "nightly": "MBAG Nightly Set",
        "regression": "MBAG Regression Set",
        "milestone": "MBAG Milestone Set",
    },
}

# Mapping: cycle_type -> pytest markers to select
CYCLE_MARKERS: Dict[str, List[str]] = {
    "nightly": ["functional", "smoke"],
    "regression": ["functional", "regression", "smoke"],
    "milestone": ["functional", "regression", "durability", "smoke"],
}


def get_test_set_name(project: str, cycle_type: str) -> str:
    """
    Get the Jira Test Set name for a given project and cycle type.

    Args:
        project: Project name ("DR64" or "MBAG").
        cycle_type: Cycle type ("nightly", "regression", "milestone").

    Returns:
        Test Set name string.
    """
    project_sets = TEST_SET_REGISTRY.get(project, {})
    return project_sets.get(cycle_type, f"{project} {cycle_type.capitalize()} Set")


def get_markers_for_cycle(cycle_type: str) -> List[str]:
    """
    Get the pytest markers to include for a given cycle type.

    Args:
        cycle_type: Cycle type ("nightly", "regression", "milestone").

    Returns:
        List of marker names.
    """
    return CYCLE_MARKERS.get(cycle_type, ["functional"])


def build_cycle_config(
    cycle_type: str,
    project: str,
    radar_type: str,
    environment: str = "coffin",
    fw_version: Optional[str] = None,
    test_set_key: str = "",
) -> TestCycleConfig:
    """
    Build a complete test cycle configuration.

    Args:
        cycle_type: One of "nightly", "regression", "milestone".
        project: Project name ("DR64" or "MBAG").
        radar_type: Radar type ("BSR32", "BSRC", "HRR").
        environment: Environment type ("coffin" or "oven").
        fw_version: Specific firmware version (for milestone).
        test_set_key: Jira Test Set key (optional override).

    Returns:
        TestCycleConfig instance.
    """
    ct = CycleType(cycle_type)
    env = EnvironmentType(environment)
    markers = get_markers_for_cycle(cycle_type)
    test_set = test_set_key or get_test_set_name(project, cycle_type)

    config = TestCycleConfig(
        cycle_type=ct,
        project=project,
        radar_type=radar_type,
        environment=env,
        fw_version=fw_version,
        test_set_key=test_set,
        markers=markers,
    )

    logger.info(
        f"Test cycle configured: {ct.value} | {project} | {radar_type} | "
        f"env={env.value} | fw={fw_version or 'latest'} | markers={markers}"
    )
    return config


@dataclass
class FrequencyAllocation:
    """Tracks frequency allocation in a coffin environment."""
    bench_id: str
    frequency_ghz: float
    in_use: bool = False


class CoffinInterferenceManager:
    """
    Manages frequency interference in coffin environments.

    A coffin can hold up to 4 radars. If two radars need to transmit
    on the same frequency, the second must wait until the first finishes
    or find an alternative bench.
    """

    def __init__(self) -> None:
        self._allocations: Dict[str, FrequencyAllocation] = {}
        self._lock_holders: Dict[float, str] = {}  # freq -> bench_id
        logger.info("CoffinInterferenceManager initialized")

    def request_frequency(
        self, bench_id: str, frequency_ghz: float
    ) -> bool:
        """
        Request exclusive use of a frequency in the coffin.

        Args:
            bench_id: Bench requesting the frequency.
            frequency_ghz: Transmission frequency in GHz.

        Returns:
            True if frequency is available and granted.
        """
        if frequency_ghz in self._lock_holders:
            holder = self._lock_holders[frequency_ghz]
            if holder != bench_id:
                logger.warning(
                    f"Frequency {frequency_ghz} GHz is in use by {holder}. "
                    f"Bench {bench_id} must wait."
                )
                return False

        self._lock_holders[frequency_ghz] = bench_id
        self._allocations[bench_id] = FrequencyAllocation(
            bench_id=bench_id,
            frequency_ghz=frequency_ghz,
            in_use=True,
        )
        logger.info(
            f"Frequency {frequency_ghz} GHz allocated to bench {bench_id}"
        )
        return True

    def release_frequency(self, bench_id: str) -> None:
        """Release frequency allocation for a bench."""
        if bench_id in self._allocations:
            freq = self._allocations[bench_id].frequency_ghz
            if freq in self._lock_holders and self._lock_holders[freq] == bench_id:
                del self._lock_holders[freq]
            del self._allocations[bench_id]
            logger.info(
                f"Frequency released from bench {bench_id}"
            )

    def is_frequency_available(self, frequency_ghz: float) -> bool:
        """Check if a frequency is currently available."""
        return frequency_ghz not in self._lock_holders

    def get_active_allocations(self) -> Dict[str, float]:
        """Get all active frequency allocations."""
        return {
            alloc.bench_id: alloc.frequency_ghz
            for alloc in self._allocations.values()
            if alloc.in_use
        }

