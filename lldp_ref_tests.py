# File: tests/functional/test_lldp.py
import time
import pytest
from src.actions import lldp_actions, power_actions

@pytest.mark.functional
def test_basic_lldp_location_change(radar_uut):
    """
    Test basic LLDP location change capability.
    Corresponds to the original 'LLDP_test'.
    """
    target_location = "FRONT_RIGHT"
    
    # 1. Enable LLDP
    lldp_actions.enable_lldp(radar_uut)
    
    current_location = lldp_actions.get_current_physical_location(radar_uut)
    
    # 2. Change location if needed
    if current_location != target_location:
        lldp_actions.change_physical_location(radar_uut, target_location, wait_time_sec=15)
        radar_uut.set_statistics_window_size(fps=10, latency=1)
        
        # Verify change
        new_location = lldp_actions.get_current_physical_location(radar_uut)
        assert new_location == target_location, f"Expected location {target_location}, but got {new_location}"
    else:
        radar_uut.set_statistics_window_size(fps=10, latency=1)

    # Note: If DR64 check is needed, it should be passed via test configuration fixtures.
    # if config.is_dr64:
    #     lldp_actions.move_to_scanning_mode(radar_uut)

@pytest.mark.functional
@pytest.mark.timeout(300) # Safety timeout for the entire test
def test_lldp_timeout_and_recovery(radar_uut, psu_control):
    """
    Test LLDP configuration survival across power cycles with timeout.
    Corresponds to the original 'LLDP_timeout_test'.
    """
    timeout_value = 60
    wait_after_wakeup = 30
    target_location = "FRONT_LEFT"

    # 1. Enable LLDP and set timeout
    lldp_actions.enable_lldp(radar_uut)
    lldp_actions.set_rloc_timeout(radar_uut, timeout_value)
    
    # 2. Hard power cycle
    power_actions.power_cycle_radar(radar_uut, psu_control)
    
    # 3. Wait for boot and wait additional stability time
    power_actions.wait_for_radar_boot(radar_uut)
    time.sleep(wait_after_wakeup)
    
    # 4. Attempt to change location after reboot
    lldp_actions.change_physical_location(radar_uut, target_location, wait_time_sec=5)
    
    # 5. Assert final state
    final_location = lldp_actions.get_current_physical_location(radar_uut)
    assert final_location == target_location, \
        f"Location mismatch after power cycle. Expected {target_location}, got {final_location}"



# File: src/actions/power_actions.py
import time
from loguru import logger

def power_cycle_radar(radar, power_control, off_wait_sec: int = 5, on_wait_sec: int = 5) -> None:
    """Performs a hard power cycle on the radar using the PDU/Power control."""
    logger.info("Initiating power cycle...")
    try:
        radar.disconnect()
    except Exception as e:
        logger.warning(f"Disconnect failed before power cycle (ignored): {e}")
        
    power_control.set_off()
    logger.info(f"Power OFF. Waiting {off_wait_sec} seconds...")
    time.sleep(off_wait_sec)
    
    power_control.start_power()
    logger.info(f"Power ON. Waiting {on_wait_sec} seconds...")
    time.sleep(on_wait_sec)

def wait_for_radar_boot(radar, max_retries: int = 20, retry_delay_sec: int = 5) -> None:
    """Polls the radar until it responds to ping and successfully connects."""
    logger.info("Waiting for radar to boot and connect...")
    for attempt in range(1, max_retries + 1):
        time.sleep(retry_delay_sec)
        try:
            if radar.ping().response:
                if radar.connect().response:
                    logger.info(f"Radar connected successfully on attempt {attempt}.")
                    return
        except Exception as e:
            logger.debug(f"Boot wait attempt {attempt}/{max_retries} failed: {e}")
            
    raise ConnectionError(f"Radar failed to boot and connect after {max_retries * retry_delay_sec} seconds.")

# File: src/actions/lldp_actions.py
import time
from loguru import logger
# יש לייבא את ה-Enums הרלוונטיים מהמודלים שלכם
# from src.models import PhysicalLocation, SetPhyLocResponseStatus, RadarState, GenericRespStatus

def enable_lldp(radar) -> None:
    """Enables LLDP state on the radar system DB."""
    logger.info("Enabling LLDP...")
    status = radar.system_db.set_lldp_state(lldp_enable=True)
    if not status:
        raise RuntimeError("Failed to enable LLDP on radar system DB.")
    logger.info("LLDP enabled successfully.")

def set_rloc_timeout(radar, timeout_sec: int) -> None:
    """Sets the RLOC timeout value in the radar EEPROM/System DB."""
    logger.info(f"Setting RLOC timeout to {timeout_sec} seconds...")
    status = radar.system_db.set_rloc_timeout(timeout=timeout_sec)
    if not status:
        raise RuntimeError(f"Failed to set RLOC timeout to {timeout_sec}.")
    logger.info("RLOC timeout set successfully.")

def change_physical_location(radar, target_location: str, wait_time_sec: int = 5) -> None:
    """Changes the radar's physical location via LLDP and waits for application."""
    logger.info(f"Requesting physical location change to: {target_location}")
    response = radar.set_physical_location(PhysicalLocation[target_location])
    
    if response.status != SetPhyLocResponseStatus.OK: # Adjust based on actual Enum
        raise RuntimeError(f"Failed to set physical location. Response status: {response.status}")
    
    logger.info(f"Location change command accepted. Waiting {wait_time_sec} seconds...")
    time.sleep(wait_time_sec)

def get_current_physical_location(radar) -> str:
    """Returns the current physical location name."""
    return radar.physical_location.name

def move_to_scanning_mode(radar, wait_time_sec: int = 8) -> None:
    """Moves the radar to SCANNING state."""
    logger.info("Moving radar to SCANNING mode...")
    response = radar.set_state(RadarState.SCANNING)
    
    if response.status != GenericRespStatus.OK:
        raise RuntimeError(f"Failed to move to SCANNING mode. Status: {response.status}")
    
    time.sleep(wait_time_sec)
    logger.info("Successfully moved to SCANNING mode.")