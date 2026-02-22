"""
Power Actions — reusable atomic actions for PSU power control.

Handles power cycling, boot waiting, and power state management
for radar test sequences. Works with both real and mock PSU drivers.

Reference: lldp_ref_tests.py → power_actions.py
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.drivers.psu_driver import PSUDriver
    from src.drivers.radar_driver_base import RadarDriverBase


def power_cycle_radar(
    radar: RadarDriverBase,
    psu: PSUDriver,
    off_wait_sec: int = 5,
    on_wait_sec: int = 5,
) -> None:
    """
    Perform a hard power cycle on the radar using the PSU.

    Sequence:
    1. Disconnect radar gracefully
    2. Turn PSU output OFF
    3. Wait off_wait_sec seconds
    4. Turn PSU output ON
    5. Wait on_wait_sec seconds

    Args:
        radar: The radar driver instance.
        psu: The PSU driver instance.
        off_wait_sec: Seconds to keep power off.
        on_wait_sec: Seconds to wait after power on.

    Raises:
        RuntimeError: If PSU control fails.
    """
    logger.info(
        f"Initiating power cycle — off={off_wait_sec}s, on={on_wait_sec}s"
    )

    # Gracefully disconnect radar
    try:
        radar.disconnect()
    except Exception as e:
        logger.warning(f"Disconnect failed before power cycle (ignored): {e}")

    # Power OFF
    if not psu.power_off():
        raise RuntimeError("PSU: Failed to power off")
    logger.info(f"Power OFF. Waiting {off_wait_sec}s...")
    time.sleep(off_wait_sec)

    # Power ON
    if not psu.power_on():
        raise RuntimeError("PSU: Failed to power on")
    logger.info(f"Power ON. Waiting {on_wait_sec}s...")
    time.sleep(on_wait_sec)

    logger.info("Power cycle complete")


def wait_for_radar_boot(
    radar: RadarDriverBase,
    max_retries: int = 20,
    retry_delay_sec: int = 5,
) -> None:
    """
    Poll the radar until it responds to ping and successfully connects.

    Args:
        radar: The radar driver instance.
        max_retries: Maximum number of connection attempts.
        retry_delay_sec: Seconds between attempts.

    Raises:
        ConnectionError: If radar fails to boot within the retry window.
    """
    logger.info(
        f"Waiting for radar to boot — max {max_retries * retry_delay_sec}s..."
    )

    for attempt in range(1, max_retries + 1):
        time.sleep(retry_delay_sec)
        try:
            if radar.ping():
                response = radar.connect()
                if response.status.value == "OK":
                    logger.info(
                        f"Radar connected successfully on attempt {attempt}"
                    )
                    return
        except Exception as e:
            logger.debug(
                f"Boot wait attempt {attempt}/{max_retries} failed: {e}"
            )

    total_wait = max_retries * retry_delay_sec
    raise ConnectionError(
        f"Radar failed to boot and connect after {total_wait} seconds"
    )


def ensure_power_on(
    psu: PSUDriver,
    expected_voltage: float = 12.0,
    tolerance: float = 0.5,
) -> bool:
    """
    Verify PSU output is on and delivering expected voltage.

    Args:
        psu: The PSU driver instance.
        expected_voltage: Expected output voltage in volts.
        tolerance: Acceptable deviation in volts.

    Returns:
        True if PSU is on and voltage is within tolerance.
    """
    measurement = psu.measure()
    if not measurement.output_enabled:
        logger.warning("PSU output is OFF — turning on")
        return psu.power_on()

    voltage_diff = abs(measurement.voltage_v - expected_voltage)
    if voltage_diff > tolerance:
        logger.warning(
            f"PSU voltage {measurement.voltage_v}V deviates from "
            f"expected {expected_voltage}V by {voltage_diff:.2f}V"
        )
        return False

    logger.debug(
        f"PSU OK: {measurement.voltage_v}V / {measurement.current_a}A"
    )
    return True

