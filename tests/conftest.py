"""
Root conftest.py — Shared Pytest fixtures and configuration.

Provides fixtures for:
- Radar UUT via driver abstraction layer (BSR32/BSRC/HRR or Mock)
- PSU control (Keysight E36233A or Mock)
- PTP synchronization (ptp4l or Mock)
- Configuration and threshold loading
- Test cycle configuration
- Xray test ID marker processing

In simulation mode (default when hardware is unavailable), all
hardware interactions are mocked transparently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import pytest
from loguru import logger

from src.config.loader import ConfigLoader
from src.drivers import create_radar_driver
from src.drivers.radar_driver_base import RadarDriverBase
from src.drivers.psu_driver import MockPSUDriver, PSUConfig, PSUDriver
from src.drivers.ptp_driver import PTPConfig, PTPDriver


# ---------------------------------------------------------------------------
# CLI Options
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options for the test framework."""
    parser.addoption(
        "--simulate",
        action="store_true",
        default=True,
        help="Run in simulation mode (mock all hardware). Default: True",
    )
    parser.addoption(
        "--radar-type",
        default="BSR32",
        choices=["BSR32", "BSRC", "HRR"],
        help="Radar type to test against. Default: BSR32",
    )
    parser.addoption(
        "--radar-ip",
        default="192.168.101.190",
        help="Radar IP address. Default: 192.168.101.190",
    )
    parser.addoption(
        "--project",
        default="DR64",
        choices=["DR64", "MBAG"],
        help="Project name. Default: DR64",
    )
    parser.addoption(
        "--cycle",
        default="nightly",
        choices=["nightly", "regression", "milestone"],
        help="Test cycle type. Default: nightly",
    )
    parser.addoption(
        "--environment",
        default="coffin",
        choices=["coffin", "oven"],
        help="Test environment. Default: coffin",
    )
    parser.addoption(
        "--fw-version",
        default=None,
        help="Specific firmware version for milestone cycle. Default: None (latest)",
    )


# ---------------------------------------------------------------------------
# Configuration Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def config_dir() -> Path:
    """Return the path to the configuration directory."""
    project_root = Path(__file__).parent.parent
    return project_root / "config"


@pytest.fixture(scope="session")
def config_loader(config_dir: Path) -> ConfigLoader:
    """Create a shared ConfigLoader instance for the test session."""
    return ConfigLoader(config_dir=config_dir)


@pytest.fixture(scope="session")
def hardware_config(config_loader: ConfigLoader) -> Dict[str, Any]:
    """Load the hardware configuration for the test session."""
    try:
        return config_loader.load("hardware_config.yaml", validate=False)
    except FileNotFoundError:
        logger.warning("hardware_config.yaml not found, using example config")
        return config_loader.load("hardware_config.example.yaml", validate=False)


@pytest.fixture(scope="session")
def thresholds_config(config_loader: ConfigLoader) -> Dict[str, Any]:
    """Load the thresholds configuration for the test session."""
    try:
        return config_loader.load("thresholds.yaml", validate=False)
    except FileNotFoundError:
        logger.warning("thresholds.yaml not found, using example thresholds")
        return config_loader.load("thresholds.example.yaml", validate=False)


@pytest.fixture(scope="session")
def test_config(request: pytest.FixtureRequest, hardware_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidated test configuration from CLI options and config files.
    Provides a single dict with all runtime parameters.
    """
    return {
        "simulate": request.config.getoption("--simulate"),
        "radar_type": request.config.getoption("--radar-type"),
        "radar_ip": request.config.getoption("--radar-ip"),
        "project": request.config.getoption("--project"),
        "cycle": request.config.getoption("--cycle"),
        "environment": request.config.getoption("--environment"),
        "fw_version": request.config.getoption("--fw-version"),
        "hardware_config": hardware_config,
    }


# ---------------------------------------------------------------------------
# Radar UUT Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def radar_uut(
    test_config: Dict[str, Any],
) -> Generator[RadarDriverBase, None, None]:
    """
    Session-scoped fixture providing a radar driver instance.

    Uses the driver factory to create the appropriate driver (BSR/HRR/Mock)
    based on CLI options. In simulation mode, always uses MockRadarDriver.
    """
    simulate = test_config["simulate"]
    radar_type = test_config["radar_type"]
    radar_ip = test_config["radar_ip"]

    driver = create_radar_driver(
        ip=radar_ip,
        radar_type=radar_type,
        simulate=simulate,
    )

    # Connect to radar
    response = driver.connect()
    if response.status.value != "OK":
        logger.error(f"Failed to connect to radar: {response.message}")
        pytest.skip(f"Radar connection failed: {response.message}")

    logger.info(
        f"Radar UUT fixture ready — type={radar_type}, ip={radar_ip}, "
        f"fw={driver.fw_version}, simulate={simulate}"
    )
    yield driver

    # Teardown
    driver.disconnect()
    logger.info("Radar UUT fixture torn down")


# ---------------------------------------------------------------------------
# PSU Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def psu_control(
    test_config: Dict[str, Any],
    hardware_config: Dict[str, Any],
) -> Generator[PSUDriver, None, None]:
    """
    Session-scoped fixture providing a PSU driver instance.

    In simulation mode, uses MockPSUDriver.
    In production, uses the real PSUDriver with file-based locking
    to prevent collisions on the shared Ethernet connection.
    """
    simulate = test_config["simulate"]
    psu_cfg = hardware_config.get("psu", {})

    if simulate:
        psu_instance = MockPSUDriver(PSUConfig(
            ip=psu_cfg.get("ip_address", "192.168.10.3"),
            port=psu_cfg.get("port", 1),
            voltage_v=psu_cfg.get("voltage_v", 12.0),
            current_limit_a=psu_cfg.get("current_limit_a", 10.0),
        ))
    else:
        psu_instance = PSUDriver(PSUConfig(
            ip=psu_cfg.get("ip_address", "192.168.10.3"),
            port=psu_cfg.get("port", 1),
            voltage_v=psu_cfg.get("voltage_v", 12.0),
            current_limit_a=psu_cfg.get("current_limit_a", 10.0),
            scpi_port=psu_cfg.get("scpi_port", 5025),
        ))

    logger.info(f"PSU fixture initialized — simulate={simulate}")
    yield psu_instance

    # Teardown: ensure PSU is in a safe state
    try:
        psu_instance.power_off()
    except Exception as e:
        logger.warning(f"PSU teardown error (ignored): {e}")
    logger.info("PSU fixture torn down")


# ---------------------------------------------------------------------------
# PTP Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ptp_sync(
    test_config: Dict[str, Any],
    hardware_config: Dict[str, Any],
) -> Generator[PTPDriver, None, None]:
    """
    Session-scoped fixture providing a PTP driver instance.

    Starts PTP synchronization at the beginning of the session
    and stops it at the end.
    """
    simulate = test_config["simulate"]
    ptp_cfg = hardware_config.get("ptp", {})

    ptp_instance = PTPDriver(PTPConfig(
        interface=ptp_cfg.get("ptp_interface", "eth0"),
        domain=ptp_cfg.get("domain", 1),
        network_transport=ptp_cfg.get("network_transport", "L2"),
        log_sync_interval=ptp_cfg.get("log_sync_interval", -4),
        log_announce_interval=ptp_cfg.get("log_announce_interval", -2),
        log_min_delay_req_interval=ptp_cfg.get("log_min_delay_req_interval", -2),
        password=ptp_cfg.get("ptp_command_password", "trio_012"),
        config_file=ptp_cfg.get("ptp_config_file", "ptp.txt"),
        sync_timeout_sec=ptp_cfg.get("sync_timeout_sec", 30),
        simulate=simulate,
    ))

    if ptp_cfg.get("enabled", True):
        success = ptp_instance.start()
        if not success and not simulate:
            logger.error("PTP synchronization failed to start")
            pytest.skip("PTP sync failed — skipping tests")

    logger.info(f"PTP fixture initialized — simulate={simulate}")
    yield ptp_instance

    # Teardown
    ptp_instance.stop()
    logger.info("PTP fixture torn down")


# ---------------------------------------------------------------------------
# Threshold Helper Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def thresholds(thresholds_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provide easy access to the thresholds dictionary."""
    return thresholds_config.get("thresholds", {})


# ---------------------------------------------------------------------------
# Xray Marker Processing
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom Pytest markers for Jira Xray integration."""
    config.addinivalue_line(
        "markers",
        "xray(test_id): Map this test to a Jira Xray Test ID",
    )
    config.addinivalue_line(
        "markers",
        "functional: Functional tests",
    )
    config.addinivalue_line(
        "markers",
        "regression: Regression tests",
    )
    config.addinivalue_line(
        "markers",
        "durability: Durability tests",
    )
    config.addinivalue_line(
        "markers",
        "smoke: Smoke tests",
    )
    config.addinivalue_line(
        "markers",
        "thermal: Thermal/oven tests",
    )
    config.addinivalue_line(
        "markers",
        "timeout: Test timeout in seconds",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """
    Process collected test items to extract Xray markers.

    This hook logs the mapping between Pytest functions and Jira Test IDs,
    which will be used by the Jira Xray integration layer for reporting.
    """
    xray_map: Dict[str, str] = {}
    for item in items:
        for marker in item.iter_markers(name="xray"):
            test_id = marker.args[0] if marker.args else None
            if test_id:
                xray_map[item.nodeid] = test_id

    if xray_map:
        logger.info(f"Xray test mappings found: {len(xray_map)}")
        for nodeid, test_id in xray_map.items():
            logger.debug(f"  {nodeid} -> {test_id}")
