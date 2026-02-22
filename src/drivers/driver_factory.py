"""
Driver Factory — creates the appropriate radar driver based on configuration.

Selects BSR / HRR / Mock driver based on radar_type and simulation flag.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from src.drivers.radar_driver_base import RadarDriverBase


# Mapping: radar_type -> project
RADAR_PROJECT_MAP = {
    "BSR32": "DR64",
    "BSRC": "DR64",
    "HRR": "MBAG",
}


def create_radar_driver(
    ip: str,
    radar_type: str,
    simulate: bool = False,
    password: Optional[str] = None,
) -> RadarDriverBase:
    """
    Factory function to create the correct radar driver.

    Args:
        ip: IP address of the radar.
        radar_type: One of "BSR32", "BSRC", "HRR".
        simulate: If True, always returns MockRadarDriver.
        password: Optional password for sudo operations (LLDP, PTP).

    Returns:
        An instance of RadarDriverBase.

    Raises:
        ValueError: If radar_type is unknown.
    """
    if radar_type not in RADAR_PROJECT_MAP:
        raise ValueError(
            f"Unknown radar_type '{radar_type}'. "
            f"Supported types: {list(RADAR_PROJECT_MAP.keys())}"
        )

    if simulate:
        from src.drivers.mock_driver import MockRadarDriver
        logger.info(f"Creating MockRadarDriver for {radar_type} at {ip}")
        return MockRadarDriver(
            ip=ip,
            radar_type=radar_type,
            is_hrr=(radar_type == "HRR"),
            password=password,
        )

    if radar_type in ("BSR32", "BSRC"):
        try:
            from src.drivers.bsr_driver import BSRDriver
            logger.info(f"Creating BSRDriver for {radar_type} at {ip}")
            return BSRDriver(
                ip=ip,
                radar_type=radar_type,
                is_hrr=False,
                password=password,
            )
        except Exception as e:
            logger.warning(f"Failed to create BSRDriver: {e}. Falling back to MockDriver.")
            from src.drivers.mock_driver import MockRadarDriver
            return MockRadarDriver(ip=ip, radar_type=radar_type, password=password)

    elif radar_type == "HRR":
        try:
            from src.drivers.hrr_driver import HRRDriver
            logger.info(f"Creating HRRDriver for {radar_type} at {ip}")
            return HRRDriver(ip=ip, radar_type=radar_type, password=password)
        except Exception as e:
            logger.warning(f"Failed to create HRRDriver: {e}. Falling back to MockDriver.")
            from src.drivers.mock_driver import MockRadarDriver
            return MockRadarDriver(ip=ip, radar_type=radar_type, is_hrr=True, password=password)

    # Should not reach here
    raise ValueError(f"Unhandled radar_type: {radar_type}")

