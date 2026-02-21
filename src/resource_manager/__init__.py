"""
Resource Manager Module.

Handles job queuing, test bench allocation, and monitoring.
Maps hardware types to available test benches and dispatches
jobs with appropriate build versions, configurations, and thresholds.
"""

from src.resource_manager.manager import (
    BenchState,
    ResourceAllocationError,
    ResourceManager,
    ResourceMetadata,
)
from src.resource_manager.health_check import HealthChecker, HealthCheckResult

__all__ = [
    "BenchState",
    "HealthChecker",
    "HealthCheckResult",
    "ResourceAllocationError",
    "ResourceManager",
    "ResourceMetadata",
]
