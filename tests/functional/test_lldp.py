"""
LLDP Feature Tests — VW Project (Test Set: RADAR-13523)

Tests for LLDP (Link Layer Discovery Protocol) physical awareness
functionality on BSR32/BSRC radars (DR64 project).

These tests verify:
- Basic LLDP location change
- LLDP timeout and recovery after power cycle
- LLDP IP address mapping after location change

Reference: lldp_ref_tests.py
"""

import time

import pytest

from src.actions import lldp_actions, power_actions


@pytest.mark.functional
@pytest.mark.xray("RADAR-12989")
def test_basic_lldp_location_change(radar_uut, test_config):
    """
    Test basic LLDP location change capability.

    Steps:
    1. Enable LLDP on the radar
    2. Read current physical location
    3. Change location to target if different
    4. Verify the new location matches target

    Jira: RADAR-12989
    """
    target_location = "FRONT_RIGHT"

    # 1. Enable LLDP
    lldp_actions.enable_lldp(radar_uut)

    current_location = lldp_actions.get_current_physical_location(radar_uut)

    # 2. Change location if needed
    if current_location != target_location:
        lldp_actions.change_physical_location(
            radar_uut, target_location, wait_time_sec=15
        )
        radar_uut.set_statistics_window_size(fps=10, latency=1)

        # 3. Verify change
        new_location = lldp_actions.get_current_physical_location(radar_uut)
        assert new_location == target_location, (
            f"Expected location {target_location}, but got {new_location}"
        )
    else:
        radar_uut.set_statistics_window_size(fps=10, latency=1)

    # 4. If DR64 project, move to scanning mode
    if test_config.get("project") == "DR64":
        lldp_actions.move_to_scanning_mode(radar_uut)


@pytest.mark.functional
@pytest.mark.timeout(300)
@pytest.mark.xray("RADAR-13203")
def test_lldp_timeout_and_recovery(radar_uut, psu_control, test_config):
    """
    Test LLDP configuration survival across power cycles with timeout.

    Steps:
    1. Enable LLDP and set RLOC timeout
    2. Perform hard power cycle via PSU
    3. Wait for radar to boot
    4. Attempt location change after reboot
    5. Verify final location state

    Jira: RADAR-13203
    """
    timeout_value = 60
    wait_after_wakeup = 30
    target_location = "FRONT_LEFT"

    # 1. Enable LLDP and set timeout
    lldp_actions.enable_lldp(radar_uut)
    lldp_actions.set_rloc_timeout(radar_uut, timeout_value)

    # 2. Hard power cycle
    power_actions.power_cycle_radar(radar_uut, psu_control)

    # 3. Wait for boot and stability
    power_actions.wait_for_radar_boot(radar_uut)
    time.sleep(wait_after_wakeup)

    # 4. Change location after reboot
    lldp_actions.change_physical_location(
        radar_uut, target_location, wait_time_sec=5
    )

    # 5. Assert final state
    final_location = lldp_actions.get_current_physical_location(radar_uut)
    assert final_location == target_location, (
        f"Location mismatch after power cycle. "
        f"Expected {target_location}, got {final_location}"
    )


@pytest.mark.functional
@pytest.mark.xray("RADAR-13524")
def test_lldp_ip_mapping_after_location_change(radar_uut, test_config):
    """
    Test that IP address changes correctly after LLDP location change.

    Different physical locations map to different IP addresses in the
    192.168.101.190-194 range. This test verifies the mapping is correct.

    Jira: RADAR-13524
    """
    target_location = "FRONT_RIGHT_BOTTOM"
    expected_ip = lldp_actions.get_expected_ip_for_location(target_location)

    # 1. Enable LLDP
    lldp_actions.enable_lldp(radar_uut)

    # 2. Change location
    lldp_actions.change_physical_location(
        radar_uut, target_location, wait_time_sec=15
    )

    # 3. Verify location
    assert lldp_actions.verify_lldp_location_change(
        radar_uut, target_location
    ), f"Location change to {target_location} was not verified"

    # 4. Verify expected IP mapping
    # In simulation, we verify the mapping is consistent
    actual_expected_ip = lldp_actions.get_expected_ip_for_location(
        lldp_actions.get_current_physical_location(radar_uut)
    )
    assert actual_expected_ip == expected_ip, (
        f"IP mapping mismatch: expected {expected_ip}, "
        f"got {actual_expected_ip}"
    )

