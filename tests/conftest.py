"""
Root conftest.py — Shared Pytest fixtures and configuration.

Provides fixtures for:
- Radar UUT connection management (mocked for PoC).
- PSU control (mocked for PoC).
- PTP synchronization (mocked for PoC).
- Configuration and threshold loading.
- Xray test ID marker processing.

These fixtures follow the design document's architecture where the
Host PC orchestrates UUT, PSU, and PTP through dedicated APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generator

import pytest
from loguru import logger

from src.actions.radar_actions import RadarActions
from src.actions.psu_actions import PSUActions
from src.actions.ptp_actions import PTPActions
from src.config.loader import ConfigLoader


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
    """
    Load the hardware configuration for the test session.

    Falls back to the example config if no production config exists.
    """
    try:
        return config_loader.load("hardware_config.yaml", validate=False)
    except FileNotFoundError:
        logger.warning("hardware_config.yaml not found, using example config")
        return config_loader.load("hardware_config.example.yaml", validate=False)


@pytest.fixture(scope="session")
def thresholds_config(config_loader: ConfigLoader) -> Dict[str, Any]:
    """
    Load the thresholds configuration for the test session.

    Falls back to the example config if no production config exists.
    """
    try:
        return config_loader.load("thresholds.yaml", validate=False)
    except FileNotFoundError:
        logger.warning("thresholds.yaml not found, using example thresholds")
        return config_loader.load("thresholds.example.yaml", validate=False)


# ---------------------------------------------------------------------------
# Radar UUT Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def radar_uut(hardware_config: Dict[str, Any]) -> Generator[RadarActions, None, None]:
    """
    Session-scoped fixture providing a RadarActions instance.

    Initializes the radar UUT at the start of the test session
    and shuts it down at the end.
    """
    uut_cfg = hardware_config.get("uut", {})
    host_cfg = hardware_config.get("host", {})

    radar = RadarActions(
        uut_ip=uut_cfg.get("ip_address", "192.168.1.100"),
        uut_port=uut_cfg.get("port", 5000),
        driver_library=host_cfg.get("driver_library"),
    )

    # Initialize connection
    result = radar.initialize()
    if not result.is_success:
        logger.error(f"Failed to initialize radar UUT: {result.error}")
        pytest.skip("Radar UUT initialization failed — skipping tests")

    logger.info("Radar UUT fixture initialized successfully")
    yield radar

    # Teardown
    radar.shutdown()
    logger.info("Radar UUT fixture torn down")


# ---------------------------------------------------------------------------
# PSU Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def psu(hardware_config: Dict[str, Any]) -> Generator[PSUActions, None, None]:
    """
    Session-scoped fixture providing a PSUActions instance.

    Powers on the PSU at the start and safely powers off at the end.
    """
    psu_cfg = hardware_config.get("psu", {})

    psu_instance = PSUActions(
        interface=psu_cfg.get("interface", "serial"),
        port=psu_cfg.get("port"),
        ip_address=psu_cfg.get("ip_address"),
        model=psu_cfg.get("model", "MockPSU"),
    )

    # Power on with default voltage from config
    voltage_range = psu_cfg.get("voltage_range", {})
    default_voltage = voltage_range.get("min", 12.0)
    current_limit = psu_cfg.get("current_limit", 5.0)

    # Don't auto-power-on; let tests control this
    logger.info("PSU fixture initialized (output OFF)")
    yield psu_instance

    # Teardown: ensure PSU is off
    if psu_instance.is_powered_on:
        psu_instance.power_off()
        logger.info("PSU powered off during teardown")


# ---------------------------------------------------------------------------
# PTP Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ptp(hardware_config: Dict[str, Any]) -> Generator[PTPActions, None, None]:
    """
    Session-scoped fixture providing a PTPActions instance.

    Starts PTP synchronization at the beginning of the session
    and stops it at the end. The radar requires valid PTP sync to operate.
    """
    ptp_cfg = hardware_config.get("ptp", {})

    if not ptp_cfg.get("enabled", True):
        logger.warning("PTP is disabled in configuration — skipping sync")
        ptp_instance = PTPActions()
        yield ptp_instance
        return

    ptp_instance = PTPActions(
        master_ip=ptp_cfg.get("master_ip", "192.168.1.1"),
        domain=ptp_cfg.get("domain", 0),
        sync_timeout_sec=ptp_cfg.get("sync_timeout_sec", 30),
    )

    # Start synchronization
    result = ptp_instance.start_sync()
    if not result.is_success:
        logger.error(f"PTP sync failed: {result.error}")
        pytest.skip("PTP synchronization failed — skipping tests")

    logger.info("PTP fixture initialized and synchronized")
    yield ptp_instance

    # Teardown
    ptp_instance.stop_sync()
    logger.info("PTP fixture torn down")


# ---------------------------------------------------------------------------
# Threshold Helper Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def thresholds(thresholds_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Provide easy access to the thresholds dictionary.

    Usage in tests::

        def test_snr(thresholds):
            snr_limits = thresholds["signal_to_noise_ratio"]
            assert measured_snr >= snr_limits["min_db"]
    """
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
