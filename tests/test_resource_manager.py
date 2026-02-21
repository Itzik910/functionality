"""
Unit Tests for the Resource Manager Module.

Covers:
- HealthChecker: mock health checks, configurable failures, retry logic.
- ResourceManager: allocation, release, concurrency, health check integration.
- ResourceMetadata: serialization.
- BenchState: state transitions.
"""

from __future__ import annotations

import pytest

from src.resource_manager.health_check import HealthChecker, HealthCheckResult
from src.resource_manager.manager import (
    BenchState,
    ResourceAllocationError,
    ResourceManager,
    ResourceMetadata,
)


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_benches_config():
    """Provide a sample test benches configuration."""
    return {
        "benches": [
            {
                "bench_id": "BENCH-001",
                "hardware_type": "radar_x_band",
                "description": "X-Band Bench 1",
                "state": "available",
                "connection": {
                    "uut_ip": "192.168.1.10",
                    "uut_port": 5000,
                    "psu_ip": "192.168.1.20",
                    "psu_port": 1,
                    "ptp_ip": "192.168.1.30",
                },
                "location": "Lab A",
                "capabilities": ["functional", "durability"],
            },
            {
                "bench_id": "BENCH-002",
                "hardware_type": "radar_x_band",
                "description": "X-Band Bench 2",
                "state": "available",
                "connection": {
                    "uut_ip": "192.168.1.11",
                    "uut_port": 5000,
                    "psu_ip": "192.168.1.21",
                    "psu_port": 2,
                    "ptp_ip": "192.168.1.31",
                },
                "location": "Lab A",
                "capabilities": ["functional"],
            },
            {
                "bench_id": "BENCH-003",
                "hardware_type": "radar_s_band",
                "description": "S-Band Bench",
                "state": "available",
                "connection": {
                    "uut_ip": "192.168.2.10",
                    "uut_port": 5000,
                    "psu_ip": "192.168.2.20",
                    "psu_port": 1,
                    "ptp_ip": "192.168.2.30",
                },
                "location": "Lab B",
            },
            {
                "bench_id": "BENCH-004",
                "hardware_type": "radar_l_band",
                "description": "L-Band Bench (maintenance)",
                "state": "maintenance",
                "connection": {
                    "uut_ip": "192.168.3.10",
                    "uut_port": 5000,
                    "psu_ip": "192.168.3.20",
                    "psu_port": 1,
                    "ptp_ip": "192.168.3.30",
                },
                "location": "Lab C",
            },
        ],
        "health_check": {
            "ping_timeout_sec": 5,
            "psu_verify_timeout_sec": 10,
            "retry_count": 2,
            "mark_offline_on_failure": True,
        },
    }


@pytest.fixture
def resource_manager(sample_benches_config):
    """Create a ResourceManager with sample config."""
    return ResourceManager(
        benches_config=sample_benches_config,
        max_concurrent_jobs=4,
    )


@pytest.fixture
def health_checker():
    """Create a HealthChecker in mock mode."""
    return HealthChecker(mock_mode=True, retry_count=2)


# ---------------------------------------------------------------------------
# HealthChecker Tests
# ---------------------------------------------------------------------------


class TestHealthChecker:
    """Tests for the HealthChecker class."""

    def test_all_checks_pass_by_default(self, health_checker):
        """In mock mode, all checks pass by default."""
        bench = {
            "bench_id": "BENCH-001",
            "connection": {"uut_ip": "1.2.3.4", "psu_ip": "1.2.3.5", "ptp_ip": "1.2.3.6"},
        }
        result = health_checker.check_bench(bench)

        assert result.healthy is True
        assert len(result.checks) == 3
        assert all(v is True for v in result.checks.values())
        assert result.failed_checks == []

    def test_configurable_ping_failure(self, health_checker):
        """Test that mock failures can be configured per bench."""
        health_checker.set_mock_failure("BENCH-001", ["ping_uut"])

        bench = {
            "bench_id": "BENCH-001",
            "connection": {"uut_ip": "1.2.3.4", "psu_ip": "1.2.3.5", "ptp_ip": "1.2.3.6"},
        }
        result = health_checker.check_bench(bench)

        assert result.healthy is False
        assert result.checks["ping_uut"] is False
        assert result.checks["verify_psu"] is True
        assert "ping_uut" in result.failed_checks

    def test_configurable_psu_failure(self, health_checker):
        """Test configuring PSU verification failure."""
        health_checker.set_mock_failure("BENCH-001", ["verify_psu"])

        bench = {
            "bench_id": "BENCH-001",
            "connection": {"uut_ip": "1.2.3.4", "psu_ip": "1.2.3.5", "ptp_ip": "1.2.3.6"},
        }
        result = health_checker.check_bench(bench)

        assert result.healthy is False
        assert result.checks["verify_psu"] is False

    def test_multiple_failures(self, health_checker):
        """Test multiple checks failing simultaneously."""
        health_checker.set_mock_failure("BENCH-001", ["ping_uut", "ptp_connectivity"])

        bench = {
            "bench_id": "BENCH-001",
            "connection": {"uut_ip": "1.2.3.4", "psu_ip": "1.2.3.5", "ptp_ip": "1.2.3.6"},
        }
        result = health_checker.check_bench(bench)

        assert result.healthy is False
        assert len(result.failed_checks) == 2

    def test_different_benches_different_results(self, health_checker):
        """Test that failures are bench-specific."""
        health_checker.set_mock_failure("BENCH-001", ["ping_uut"])

        bench1 = {"bench_id": "BENCH-001", "connection": {"uut_ip": "1.2.3.4"}}
        bench2 = {"bench_id": "BENCH-002", "connection": {"uut_ip": "1.2.3.5"}}

        assert health_checker.check_bench(bench1).healthy is False
        assert health_checker.check_bench(bench2).healthy is True

    def test_clear_mock_failures(self, health_checker):
        """Test clearing mock failures restores healthy status."""
        health_checker.set_mock_failure("BENCH-001", ["ping_uut"])

        bench = {"bench_id": "BENCH-001", "connection": {"uut_ip": "1.2.3.4"}}
        assert health_checker.check_bench(bench).healthy is False

        health_checker.clear_mock_failures()
        assert health_checker.check_bench(bench).healthy is True

    def test_result_details(self, health_checker):
        """Test that result includes bench details."""
        bench = {
            "bench_id": "BENCH-001",
            "connection": {"uut_ip": "1.2.3.4", "psu_ip": "1.2.3.5"},
        }
        result = health_checker.check_bench(bench)

        assert result.details["bench_id"] == "BENCH-001"
        assert result.details["checks_run"] == 3
        assert result.details["checks_passed"] == 3


# ---------------------------------------------------------------------------
# ResourceManager Tests
# ---------------------------------------------------------------------------


class TestResourceManager:
    """Tests for the ResourceManager class."""

    def test_init_loads_benches(self, resource_manager):
        """Test that initialization loads bench inventory."""
        statuses = resource_manager.get_all_bench_statuses()
        assert len(statuses) == 4

    def test_request_resource_success(self, resource_manager):
        """Test successful resource allocation."""
        metadata = resource_manager.request_resource("radar_x_band", job_id="JOB-1")

        assert metadata.bench_id in ("BENCH-001", "BENCH-002")
        assert metadata.hardware_type == "radar_x_band"
        assert metadata.uut_ip in ("192.168.1.10", "192.168.1.11")
        assert metadata.allocated_at > 0

    def test_request_resource_returns_metadata(self, resource_manager):
        """Test that metadata contains all connection details."""
        metadata = resource_manager.request_resource("radar_s_band")

        assert metadata.bench_id == "BENCH-003"
        assert metadata.uut_ip == "192.168.2.10"
        assert metadata.psu_ip == "192.168.2.20"
        assert metadata.ptp_ip == "192.168.2.30"
        assert metadata.location == "Lab B"

    def test_request_sets_bench_busy(self, resource_manager):
        """Test that allocation sets bench to BUSY."""
        metadata = resource_manager.request_resource("radar_s_band")

        status = resource_manager.get_bench_status(metadata.bench_id)
        assert status["state"] == "busy"

    def test_release_resource(self, resource_manager):
        """Test releasing a bench makes it available again."""
        metadata = resource_manager.request_resource("radar_s_band")
        assert resource_manager.current_allocations == 1

        released = resource_manager.release_resource(metadata.bench_id)
        assert released is True
        assert resource_manager.current_allocations == 0

        status = resource_manager.get_bench_status(metadata.bench_id)
        assert status["state"] == "available"

    def test_release_unallocated_returns_false(self, resource_manager):
        """Test releasing a non-allocated bench returns False."""
        assert resource_manager.release_resource("BENCH-001") is False

    def test_no_available_bench_raises(self, resource_manager):
        """Test that requesting unavailable type raises error."""
        with pytest.raises(ResourceAllocationError, match="No available bench"):
            resource_manager.request_resource("radar_unknown_type")

    def test_maintenance_bench_not_allocated(self, resource_manager):
        """Test that benches in maintenance state are not allocated."""
        with pytest.raises(ResourceAllocationError):
            resource_manager.request_resource("radar_l_band")

    def test_concurrent_allocation(self, resource_manager):
        """Test allocating multiple benches of the same type."""
        meta1 = resource_manager.request_resource("radar_x_band", job_id="JOB-1")
        meta2 = resource_manager.request_resource("radar_x_band", job_id="JOB-2")

        assert meta1.bench_id != meta2.bench_id
        assert resource_manager.current_allocations == 2

    def test_all_benches_allocated_raises(self, resource_manager):
        """Test that no bench available after all are allocated."""
        resource_manager.request_resource("radar_x_band")
        resource_manager.request_resource("radar_x_band")

        # Both x_band benches allocated
        with pytest.raises(ResourceAllocationError, match="No available bench"):
            resource_manager.request_resource("radar_x_band")

    def test_max_concurrent_jobs_enforced(self, sample_benches_config):
        """Test that max concurrent jobs limit is enforced."""
        rm = ResourceManager(
            benches_config=sample_benches_config,
            max_concurrent_jobs=2,
        )

        rm.request_resource("radar_x_band", job_id="JOB-1")
        rm.request_resource("radar_x_band", job_id="JOB-2")

        with pytest.raises(ResourceAllocationError, match="Maximum concurrent jobs"):
            rm.request_resource("radar_s_band")

    def test_health_check_failure_skips_bench(self, sample_benches_config):
        """Test that a bench failing health check is skipped for the next one."""
        checker = HealthChecker(mock_mode=True, retry_count=1)
        checker.set_mock_failure("BENCH-001", ["ping_uut"])

        rm = ResourceManager(
            benches_config=sample_benches_config,
            max_concurrent_jobs=4,
            health_checker=checker,
        )

        metadata = rm.request_resource("radar_x_band")
        # Should skip BENCH-001 and allocate BENCH-002
        assert metadata.bench_id == "BENCH-002"

    def test_health_check_failure_marks_offline(self, sample_benches_config):
        """Test that failed health check marks bench as offline."""
        checker = HealthChecker(mock_mode=True, retry_count=1)
        checker.set_mock_failure("BENCH-001", ["ping_uut"])

        rm = ResourceManager(
            benches_config=sample_benches_config,
            max_concurrent_jobs=4,
            health_checker=checker,
        )

        rm.request_resource("radar_x_band")

        status = rm.get_bench_status("BENCH-001")
        assert status["state"] == "offline"

    def test_all_candidates_fail_health_check(self, sample_benches_config):
        """Test error when all candidates fail health checks."""
        checker = HealthChecker(mock_mode=True, retry_count=1)
        checker.set_mock_failure("BENCH-001", ["ping_uut"])
        checker.set_mock_failure("BENCH-002", ["verify_psu"])

        rm = ResourceManager(
            benches_config=sample_benches_config,
            max_concurrent_jobs=4,
            health_checker=checker,
        )

        with pytest.raises(ResourceAllocationError, match="failed health checks"):
            rm.request_resource("radar_x_band")

    def test_skip_health_check(self, resource_manager):
        """Test allocation without health check."""
        metadata = resource_manager.request_resource(
            "radar_x_band", skip_health_check=True
        )
        assert metadata.bench_id in ("BENCH-001", "BENCH-002")
        assert metadata.health_check_result is None

    def test_get_bench_status(self, resource_manager):
        """Test querying bench status."""
        status = resource_manager.get_bench_status("BENCH-001")

        assert status is not None
        assert status["bench_id"] == "BENCH-001"
        assert status["hardware_type"] == "radar_x_band"
        assert status["state"] == "available"

    def test_get_bench_status_not_found(self, resource_manager):
        """Test querying unknown bench returns None."""
        assert resource_manager.get_bench_status("BENCH-999") is None

    def test_get_available_count(self, resource_manager):
        """Test counting available benches."""
        assert resource_manager.get_available_count() == 3  # 4 total, 1 maintenance
        assert resource_manager.get_available_count("radar_x_band") == 2
        assert resource_manager.get_available_count("radar_s_band") == 1
        assert resource_manager.get_available_count("radar_l_band") == 0  # maintenance

    def test_set_bench_state(self, resource_manager):
        """Test manually setting bench state."""
        result = resource_manager.set_bench_state("BENCH-004", BenchState.AVAILABLE)
        assert result is True

        status = resource_manager.get_bench_status("BENCH-004")
        assert status["state"] == "available"

    def test_set_bench_state_not_found(self, resource_manager):
        """Test setting state of unknown bench returns False."""
        assert resource_manager.set_bench_state("BENCH-999", BenchState.AVAILABLE) is False

    def test_max_concurrent_jobs_property(self, resource_manager):
        """Test max_concurrent_jobs property."""
        assert resource_manager.max_concurrent_jobs == 4

    def test_current_allocations_property(self, resource_manager):
        """Test current_allocations property."""
        assert resource_manager.current_allocations == 0

        resource_manager.request_resource("radar_x_band")
        assert resource_manager.current_allocations == 1

    def test_empty_config(self):
        """Test creating a ResourceManager with no benches."""
        rm = ResourceManager()
        assert rm.get_available_count() == 0
        assert rm.current_allocations == 0


# ---------------------------------------------------------------------------
# ResourceMetadata Tests
# ---------------------------------------------------------------------------


class TestResourceMetadata:
    """Tests for the ResourceMetadata dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        meta = ResourceMetadata(
            bench_id="BENCH-001",
            hardware_type="radar_x_band",
            uut_ip="192.168.1.10",
            psu_ip="192.168.1.20",
            ptp_ip="192.168.1.30",
            location="Lab A",
            allocated_at=1234567890.0,
        )
        d = meta.to_dict()

        assert d["bench_id"] == "BENCH-001"
        assert d["hardware_type"] == "radar_x_band"
        assert d["uut_ip"] == "192.168.1.10"
        assert d["allocated_at"] == 1234567890.0
        assert d["health_check_passed"] is None  # No health check

    def test_to_dict_with_health_check(self):
        """Test serialization includes health check result."""
        health = HealthCheckResult(bench_id="BENCH-001", healthy=True)
        meta = ResourceMetadata(
            bench_id="BENCH-001",
            health_check_result=health,
        )
        d = meta.to_dict()
        assert d["health_check_passed"] is True


# ---------------------------------------------------------------------------
# BenchState Tests
# ---------------------------------------------------------------------------


class TestBenchState:
    """Tests for the BenchState enum."""

    def test_all_states_exist(self):
        """Test that all expected states are defined."""
        assert BenchState.AVAILABLE.value == "available"
        assert BenchState.BUSY.value == "busy"
        assert BenchState.MAINTENANCE.value == "maintenance"
        assert BenchState.OFFLINE.value == "offline"

    def test_state_from_string(self):
        """Test creating state from string."""
        assert BenchState("available") == BenchState.AVAILABLE
        assert BenchState("busy") == BenchState.BUSY

