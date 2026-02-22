"""
LLDP Actions — reusable atomic actions for LLDP / Physical Awareness.

Handles LLDP enable, location change, timeout configuration, and
scanning mode transitions. Works with BSR32/BSRC radars that support
LLDP via the bsr_apis system_db interface.

Important: LLDP location changes can cause the radar to change its
IP address (192.168.101.190-194 range), which triggers a reconnection
on a different IP. The framework must handle this transparently.

Reference: lldp_ref_tests.py → lldp_actions.py
Reference: bsr_apis_5.4.1_user_guide.html → LLDP section
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.drivers.radar_driver_base import RadarDriverBase


# Valid physical locations for LLDP
VALID_LOCATIONS = [
    "DEFAULT",
    "FRONT_CENTER_BOTTOM",
    "FRONT_RIGHT_BOTTOM",
    "FRONT_LEFT_BOTTOM",
    "REAR_RIGHT_BOTTOM",
    "REAR_LEFT_BOTTOM",
    "FRONT_RIGHT",
    "FRONT_LEFT",
]

# IP address mapping per physical location (configurable)
LOCATION_IP_MAP = {
    "DEFAULT": "192.168.101.190",
    "FRONT_CENTER_BOTTOM": "192.168.101.190",
    "FRONT_RIGHT_BOTTOM": "192.168.101.191",
    "FRONT_LEFT_BOTTOM": "192.168.101.192",
    "REAR_RIGHT_BOTTOM": "192.168.101.193",
    "REAR_LEFT_BOTTOM": "192.168.101.194",
    "FRONT_RIGHT": "192.168.101.191",
    "FRONT_LEFT": "192.168.101.192",
}


def enable_lldp(radar: RadarDriverBase) -> None:
    """
    Enable LLDP state on the radar system DB.

    This must be called before any location change operations.

    Args:
        radar: Radar driver instance (must support LLDP).

    Raises:
        RuntimeError: If LLDP cannot be enabled.
    """
    logger.info("Enabling LLDP on radar...")
    if not radar.enable_lldp():
        raise RuntimeError("Failed to enable LLDP on radar system DB")
    logger.info("LLDP enabled successfully")


def set_rloc_timeout(radar: RadarDriverBase, timeout_sec: int) -> None:
    """
    Set the RLOC (Remote Location) timeout in the radar's system DB.

    This timeout determines how long the radar waits before reverting
    to default location if no LLDP messages are received.

    Args:
        radar: Radar driver instance.
        timeout_sec: Timeout value in seconds.

    Raises:
        RuntimeError: If timeout cannot be set.
    """
    logger.info(f"Setting RLOC timeout to {timeout_sec}s...")
    if not radar.set_rloc_timeout(timeout_sec):
        raise RuntimeError(f"Failed to set RLOC timeout to {timeout_sec}s")
    logger.info("RLOC timeout set successfully")


def change_physical_location(
    radar: RadarDriverBase,
    target_location: str,
    wait_time_sec: int = 5,
) -> None:
    """
    Change the radar's physical location via LLDP.

    WARNING: This operation may cause the radar to change its IP address.
    After calling this, you may need to reconnect to the radar on a
    different IP. The new IP depends on the physical location mapping.

    Args:
        radar: Radar driver instance.
        target_location: Target location name (e.g., "FRONT_RIGHT").
        wait_time_sec: Seconds to wait after the change for it to take effect.

    Raises:
        ValueError: If target_location is not a valid location.
        RuntimeError: If location change command fails.
    """
    if target_location not in VALID_LOCATIONS:
        raise ValueError(
            f"Invalid location '{target_location}'. "
            f"Valid: {VALID_LOCATIONS}"
        )

    logger.info(f"Requesting physical location change to: {target_location}")
    success = radar.set_physical_location(target_location)

    if not success:
        raise RuntimeError(
            f"Failed to set physical location to {target_location}"
        )

    logger.info(
        f"Location change command accepted. Waiting {wait_time_sec}s "
        "for change to take effect..."
    )
    time.sleep(wait_time_sec)


def get_current_physical_location(radar: RadarDriverBase) -> str:
    """
    Get the radar's current physical location.

    Returns:
        Physical location name as string (e.g., "FRONT_RIGHT").
    """
    location = radar.get_physical_location()
    logger.debug(f"Current physical location: {location}")
    return location


def get_expected_ip_for_location(location: str) -> str:
    """
    Get the expected IP address for a given physical location.

    Args:
        location: Physical location name.

    Returns:
        Expected IP address string.
    """
    return LOCATION_IP_MAP.get(location, "192.168.101.190")


def move_to_scanning_mode(
    radar: RadarDriverBase,
    wait_time_sec: int = 8,
) -> None:
    """
    Move the radar to SCANNING state.

    Required after LLDP location change for DR64 project radars
    to start normal operation.

    Args:
        radar: Radar driver instance.
        wait_time_sec: Seconds to wait after state change.

    Raises:
        RuntimeError: If state change fails.
    """
    logger.info("Moving radar to SCANNING mode...")
    success = radar.set_state("SCANNING")

    if not success:
        raise RuntimeError("Failed to move radar to SCANNING mode")

    time.sleep(wait_time_sec)
    logger.info("Successfully moved to SCANNING mode")


def verify_lldp_location_change(
    radar: RadarDriverBase,
    expected_location: str,
) -> bool:
    """
    Verify that the radar's physical location matches the expected value.

    Args:
        radar: Radar driver instance.
        expected_location: Expected location name.

    Returns:
        True if current location matches expected.
    """
    current = get_current_physical_location(radar)
    match = current == expected_location
    if match:
        logger.info(f"Location verified: {current}")
    else:
        logger.error(
            f"Location mismatch: expected={expected_location}, actual={current}"
        )
    return match

