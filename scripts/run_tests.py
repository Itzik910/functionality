#!/usr/bin/env python
"""
Run Tests Script.

Utility script for executing test suites with proper configuration.
Integrates with the Resource Manager for bench allocation and
Jira Xray for test set fetching.

Usage:
    python scripts/run_tests.py --suite functional --config config/hardware_config.yaml
    python scripts/run_tests.py --suite functional --hardware-type radar_x_band
    python scripts/run_tests.py --suite all --test-set RADAR-500 --jira-url https://jira.example.com
"""

import argparse
import sys
import time

from loguru import logger

# Add project root to path
sys.path.insert(0, ".")

from src.config.loader import ConfigLoader
from src.resource_manager.manager import ResourceManager, ResourceAllocationError


def parse_args():
    """Parse command-line arguments for test execution."""
    parser = argparse.ArgumentParser(
        description="Radar Automated Test Environment — Test Runner"
    )
    parser.add_argument(
        "--suite",
        choices=["functional", "durability", "regression", "integration", "all"],
        default="all",
        help="Test suite to execute (default: all)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/hardware_config.yaml",
        help="Path to hardware configuration file",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default="config/thresholds.yaml",
        help="Path to thresholds file",
    )
    parser.add_argument(
        "--allure-dir",
        type=str,
        default="allure-results",
        help="Directory for Allure results output",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    # --- Resource Manager arguments ---
    parser.add_argument(
        "--hardware-type",
        type=str,
        default="",
        help="Hardware type to allocate (e.g., radar_x_band)",
    )
    parser.add_argument(
        "--benches-config",
        type=str,
        default="config/test_benches.yaml",
        help="Path to test benches configuration file",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip pre-flight health checks on bench allocation",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        default="",
        help="Job identifier for resource tracking",
    )
    # --- Jira Xray arguments ---
    parser.add_argument(
        "--test-set",
        type=str,
        default="",
        help="Jira Xray Test Set key to fetch test IDs from",
    )
    parser.add_argument(
        "--jira-url",
        type=str,
        default="",
        help="Jira instance base URL for Xray integration",
    )
    return parser.parse_args()


def allocate_bench(args, config_loader: ConfigLoader):
    """
    Allocate a test bench using the Resource Manager.

    Args:
        args: Parsed command-line arguments.
        config_loader: ConfigLoader instance.

    Returns:
        Tuple of (ResourceManager, ResourceMetadata) or (None, None) if skipped.
    """
    if not args.hardware_type:
        logger.info("[Runner] No --hardware-type specified, skipping bench allocation")
        return None, None

    logger.info(f"[Runner] Loading bench config from: {args.benches_config}")

    try:
        benches_config = config_loader.load(
            args.benches_config,
            schema_name="test_benches_schema",
            validate=True,
        )
    except FileNotFoundError:
        logger.warning(
            f"[Runner] Benches config not found: {args.benches_config}. "
            f"Skipping bench allocation."
        )
        return None, None
    except Exception as e:
        logger.error(f"[Runner] Failed to load bench config: {e}")
        return None, None

    # Get max_concurrent_jobs from environment config if available
    max_jobs = 4
    try:
        env_config = config_loader.load(
            "test_environment.example.yaml",
            schema_name="test_environment_schema",
        )
        max_jobs = env_config.get("resource_manager", {}).get(
            "max_concurrent_jobs", 4
        )
    except Exception:
        pass

    rm = ResourceManager(
        benches_config=benches_config,
        max_concurrent_jobs=max_jobs,
    )

    try:
        metadata = rm.request_resource(
            hardware_type=args.hardware_type,
            job_id=args.job_id,
            skip_health_check=args.skip_health_check,
        )
        logger.info(
            f"[Runner] Bench allocated: {metadata.bench_id} "
            f"(UUT: {metadata.uut_ip}, PSU: {metadata.psu_ip})"
        )
        return rm, metadata
    except ResourceAllocationError as e:
        logger.error(f"[Runner] Bench allocation failed: {e}")
        return rm, None


def main():
    """Main entry point for the test runner."""
    args = parse_args()

    logger.info("=" * 60)
    logger.info("[Runner] Radar Automated Test Environment — Test Runner")
    logger.info("=" * 60)
    logger.info(f"[Runner] Suite: {args.suite}")
    logger.info(f"[Runner] Config: {args.config}")
    logger.info(f"[Runner] Thresholds: {args.thresholds}")
    logger.info(f"[Runner] Allure Dir: {args.allure_dir}")

    config_loader = ConfigLoader()

    # --- Step 1: Allocate bench (if hardware_type specified) ---
    rm, resource_metadata = allocate_bench(args, config_loader)

    if args.hardware_type and resource_metadata is None:
        logger.error("[Runner] Cannot proceed without a bench. Exiting.")
        return 1

    if resource_metadata:
        logger.info(f"[Runner] Resource Metadata: {resource_metadata.to_dict()}")

    # --- Step 2: Build Pytest command ---
    pytest_args = []

    # Select suite
    if args.suite == "all":
        pytest_args.append("tests/")
    else:
        pytest_args.append(f"tests/{args.suite}/")

    # Allure reporting
    pytest_args.extend(["--alluredir", args.allure_dir])

    # Verbosity
    if args.verbose:
        pytest_args.append("-v")

    logger.info(f"[Runner] Pytest args: {pytest_args}")

    # --- Step 3: Execute tests ---
    # TODO: Replace with actual pytest.main(pytest_args) call
    logger.info("[Runner] Test execution placeholder — would run pytest here")
    exit_code = 0

    # --- Step 4: Release bench ---
    if rm and resource_metadata:
        rm.release_resource(resource_metadata.bench_id)
        logger.info(f"[Runner] Bench {resource_metadata.bench_id} released")

    logger.info(f"[Runner] Finished with exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
