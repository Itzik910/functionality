"""
Unit Tests for Radar Driver Abstraction Layer.

Covers:
- MockRadarDriver: full simulation behavior
- BSRDriver / HRRDriver: graceful fallback when APIs unavailable
- DriverFactory: correct driver selection and fallback
- PSUDriver / MockPSUDriver: power control and locking
- PTPDriver: simulation mode
- FirmwareManager: mock download/extract flows
"""

from __future__ import annotations

import os
import time

import pytest

from src.drivers.mock_driver import MockRadarDriver
from src.drivers.driver_factory import create_radar_driver, RADAR_PROJECT_MAP
from src.drivers.radar_driver_base import (
    ConnectResponse,
    ConnectStatus,
    DetectionData,
    HeartbeatData,
    PointCloudFrame,
    RadarDriverBase,
    StatisticsData,
)
from src.drivers.psu_driver import MockPSUDriver, PSUConfig, PSUMeasurement
from src.drivers.ptp_driver import PTPConfig, PTPDriver, PTPStatus
from src.drivers.fw_manager import FirmwareManager, FWVersion


# ===========================================================================
# MockRadarDriver Tests
# ===========================================================================


class TestMockRadarDriver:
    """Tests for MockRadarDriver simulation layer."""

    def test_init_defaults(self):
        driver = MockRadarDriver()
        assert driver.ip == "192.168.101.190"
        assert driver.radar_type == "BSR32"
        assert not driver.is_connected
        assert driver.fw_version.startswith("v5")

    def test_init_hrr(self):
        driver = MockRadarDriver(radar_type="HRR", is_hrr=True)
        assert driver.radar_type == "HRR"
        assert driver.is_hrr
        assert driver.fw_version.startswith("v4")

    def test_connect_success(self):
        driver = MockRadarDriver()
        response = driver.connect()
        assert response.status == ConnectStatus.OK
        assert driver.is_connected
        assert "Mock" in response.message

    def test_connect_failure(self):
        driver = MockRadarDriver(fail_connect=True)
        response = driver.connect()
        assert response.status == ConnectStatus.NO_PING
        assert not driver.is_connected

    def test_disconnect(self):
        driver = MockRadarDriver()
        driver.connect()
        assert driver.is_connected
        driver.disconnect()
        assert not driver.is_connected

    def test_ping_success(self):
        driver = MockRadarDriver()
        assert driver.ping() is True

    def test_ping_failure(self):
        driver = MockRadarDriver(fail_ping=True)
        assert driver.ping() is False

    def test_heartbeat_when_connected(self):
        driver = MockRadarDriver()
        driver.connect()
        hb = driver.get_heartbeat()
        assert hb is not None
        assert isinstance(hb, HeartbeatData)
        assert hb.beat_id == 1
        assert hb.status == "OK"
        assert "tsip_0" in hb.temperatures

    def test_heartbeat_when_disconnected(self):
        driver = MockRadarDriver()
        assert driver.get_heartbeat() is None

    def test_point_cloud_when_connected(self):
        driver = MockRadarDriver()
        driver.connect()
        pc = driver.get_point_cloud()
        assert pc is not None
        assert isinstance(pc, PointCloudFrame)
        assert pc.valid_detections > 0
        assert len(pc.detections) > 0
        det = pc.detections[0]
        assert isinstance(det, DetectionData)

    def test_point_cloud_when_disconnected(self):
        driver = MockRadarDriver()
        assert driver.get_point_cloud() is None

    def test_statistics(self):
        driver = MockRadarDriver()
        stats = driver.get_statistics()
        assert isinstance(stats, StatisticsData)
        assert stats.fps_mean == 10.0

    def test_fw_update(self):
        driver = MockRadarDriver()
        assert driver.update_fw(modality="DR64") is True

    def test_reset(self):
        driver = MockRadarDriver()
        driver.connect()
        driver.set_state("SCANNING")
        assert driver.state == "SCANNING"
        driver.reset()
        assert driver.state == "STANDBY"

    def test_set_state_valid(self):
        driver = MockRadarDriver()
        assert driver.set_state("SCANNING") is True
        assert driver.state == "SCANNING"

    def test_set_state_invalid(self):
        driver = MockRadarDriver()
        assert driver.set_state("INVALID") is False

    def test_recording(self):
        driver = MockRadarDriver()
        driver.connect()
        assert driver.start_recording("/tmp/rec") is True
        assert driver.start_recording("/tmp/rec") is False  # Already recording
        assert driver.stop_recording() is True

    def test_lldp_location(self):
        driver = MockRadarDriver()
        assert driver.get_physical_location() == "FRONT_CENTER_BOTTOM"
        assert driver.set_physical_location("FRONT_RIGHT") is True
        assert driver.get_physical_location() == "FRONT_RIGHT"
        assert driver.set_physical_location("INVALID_LOC") is False

    def test_enable_lldp(self):
        driver = MockRadarDriver()
        assert driver.enable_lldp() is True

    def test_rloc_timeout(self):
        driver = MockRadarDriver()
        assert driver.set_rloc_timeout(60) is True

    def test_context_manager(self):
        with MockRadarDriver() as driver:
            driver.connect()
            assert driver.is_connected
        assert not driver.is_connected


# ===========================================================================
# Driver Factory Tests
# ===========================================================================


class TestDriverFactory:
    """Tests for driver factory function."""

    def test_simulate_bsr32(self):
        driver = create_radar_driver("192.168.101.190", "BSR32", simulate=True)
        assert isinstance(driver, MockRadarDriver)
        assert driver.radar_type == "BSR32"

    def test_simulate_bsrc(self):
        driver = create_radar_driver("192.168.101.191", "BSRC", simulate=True)
        assert isinstance(driver, MockRadarDriver)
        assert driver.radar_type == "BSRC"

    def test_simulate_hrr(self):
        driver = create_radar_driver("192.168.101.192", "HRR", simulate=True)
        assert isinstance(driver, MockRadarDriver)
        assert driver.radar_type == "HRR"
        assert driver.is_hrr

    def test_unknown_radar_type(self):
        with pytest.raises(ValueError, match="Unknown radar_type"):
            create_radar_driver("192.168.1.1", "UNKNOWN_RADAR", simulate=True)

    def test_project_mapping(self):
        assert RADAR_PROJECT_MAP["BSR32"] == "DR64"
        assert RADAR_PROJECT_MAP["BSRC"] == "DR64"
        assert RADAR_PROJECT_MAP["HRR"] == "MBAG"

    def test_real_bsr_fallback_to_mock(self):
        """When bsr_apis is not installed, factory should fall back to mock."""
        driver = create_radar_driver("192.168.101.190", "BSR32", simulate=False)
        # Should get either BSRDriver or MockRadarDriver (fallback)
        assert isinstance(driver, RadarDriverBase)

    def test_real_hrr_fallback_to_mock(self):
        """When hrr_apis is not installed, factory should fall back to mock."""
        driver = create_radar_driver("192.168.101.190", "HRR", simulate=False)
        assert isinstance(driver, RadarDriverBase)


# ===========================================================================
# MockPSUDriver Tests
# ===========================================================================


class TestMockPSUDriver:
    """Tests for MockPSUDriver simulation layer."""

    def test_init(self):
        psu = MockPSUDriver()
        assert psu.config.simulate is True

    def test_power_on_off(self):
        psu = MockPSUDriver()
        assert psu.power_on() is True
        meas = psu.measure()
        assert meas.output_enabled is True
        assert meas.voltage_v == 12.0

        assert psu.power_off() is True
        meas = psu.measure()
        assert meas.output_enabled is False
        assert meas.voltage_v == 0.0

    def test_measure_off(self):
        psu = MockPSUDriver()
        meas = psu.measure()
        assert meas.voltage_v == 0.0
        assert meas.current_a == 0.0
        assert meas.output_enabled is False

    def test_measure_on(self):
        psu = MockPSUDriver()
        psu.power_on()
        meas = psu.measure()
        assert meas.voltage_v == 12.0
        assert meas.current_a > 0
        assert meas.power_w > 0

    def test_set_voltage_valid(self):
        psu = MockPSUDriver()
        assert psu.set_voltage(15.0) is True

    def test_set_voltage_invalid(self):
        psu = MockPSUDriver()
        assert psu.set_voltage(35.0) is False  # Over MAX_VOLTAGE
        assert psu.set_voltage(-1.0) is False

    def test_set_current_valid(self):
        psu = MockPSUDriver()
        assert psu.set_current_limit(5.0) is True

    def test_set_current_invalid(self):
        psu = MockPSUDriver()
        assert psu.set_current_limit(25.0) is False  # Over MAX_CURRENT

    def test_identify(self):
        psu = MockPSUDriver()
        assert "E36233A" in psu.identify()

    def test_check_errors(self):
        psu = MockPSUDriver()
        assert "No error" in psu.check_errors()

    def test_power_cycle(self):
        psu = MockPSUDriver()
        psu.power_on()
        assert psu.power_cycle(off_duration_sec=0.01) is True

    def test_custom_config(self):
        config = PSUConfig(
            ip="192.168.10.3",
            port=2,
            voltage_v=24.0,
            current_limit_a=5.0,
        )
        psu = MockPSUDriver(config)
        psu.power_on()
        meas = psu.measure()
        assert meas.voltage_v == 24.0
        assert meas.port == 2


# ===========================================================================
# PTPDriver Tests (Simulation)
# ===========================================================================


class TestPTPDriverSimulation:
    """Tests for PTPDriver in simulation mode."""

    def test_init(self):
        ptp = PTPDriver(PTPConfig(simulate=True))
        assert not ptp.is_running
        assert not ptp.is_synced

    def test_start_stop(self):
        ptp = PTPDriver(PTPConfig(simulate=True))
        assert ptp.start() is True
        assert ptp.is_running
        assert ptp.is_synced

        assert ptp.stop() is True
        assert not ptp.is_running
        assert not ptp.is_synced

    def test_status_when_running(self):
        ptp = PTPDriver(PTPConfig(simulate=True))
        ptp.start()
        status = ptp.get_status()
        assert isinstance(status, PTPStatus)
        assert status.running is True
        assert status.synced is True
        assert status.state == "SLAVE"
        assert status.offset_ns > 0

    def test_status_when_stopped(self):
        ptp = PTPDriver(PTPConfig(simulate=True))
        status = ptp.get_status()
        assert status.running is False
        assert status.synced is False

    def test_context_manager(self):
        with PTPDriver(PTPConfig(simulate=True)) as ptp:
            assert ptp.is_running
        assert not ptp.is_running

    def test_double_start(self):
        ptp = PTPDriver(PTPConfig(simulate=True))
        ptp.start()
        assert ptp.start() is True  # Should not fail


# ===========================================================================
# FirmwareManager Tests (Simulation)
# ===========================================================================


class TestFirmwareManagerSimulation:
    """Tests for FirmwareManager in simulation mode."""

    def test_init(self):
        fm = FirmwareManager(gitlab_token="test_token", simulate=True)
        assert fm._simulate is True

    def test_get_release_versions(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        versions = fm.get_release_versions()
        assert len(versions) > 0
        assert "v5.4.1" in versions

    def test_download_release(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        fw = fm.download_release("v5.4.1")
        assert fw is not None
        assert isinstance(fw, FWVersion)
        assert fw.tag_name == "v5.4.1"
        assert fw.is_nightly is False

    def test_download_latest_nightly(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        fw = fm.download_latest_nightly()
        assert fw is not None
        assert fw.is_nightly is True
        assert fw.tag_name == "nightly-latest"

    def test_download_for_cycle_nightly(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        fw = fm.download_for_cycle("nightly")
        assert fw is not None
        assert fw.is_nightly is True

    def test_download_for_cycle_milestone(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        fw = fm.download_for_cycle("milestone", version="v5.4.1")
        assert fw is not None
        assert fw.tag_name == "v5.4.1"

    def test_download_for_cycle_unknown(self):
        fm = FirmwareManager(gitlab_token="test", simulate=True)
        fw = fm.download_for_cycle("unknown_cycle")
        assert fw is None


# ===========================================================================
# Test Cycle Tests
# ===========================================================================


class TestTestCycle:
    """Tests for test cycle configuration."""

    def test_build_cycle_config_nightly(self):
        from src.test_cycle import build_cycle_config, CycleType
        config = build_cycle_config(
            cycle_type="nightly",
            project="DR64",
            radar_type="BSR32",
        )
        assert config.cycle_type == CycleType.NIGHTLY
        assert config.project == "DR64"
        assert "functional" in config.markers

    def test_build_cycle_config_milestone(self):
        from src.test_cycle import build_cycle_config, CycleType
        config = build_cycle_config(
            cycle_type="milestone",
            project="MBAG",
            radar_type="HRR",
            fw_version="v4.6.5",
        )
        assert config.cycle_type == CycleType.MILESTONE
        assert config.fw_version == "v4.6.5"
        assert "durability" in config.markers

    def test_get_test_set_name(self):
        from src.test_cycle import get_test_set_name
        assert get_test_set_name("DR64", "nightly") == "VW Nightly Set"
        assert get_test_set_name("MBAG", "regression") == "MBAG Regression Set"

    def test_coffin_interference_manager(self):
        from src.test_cycle import CoffinInterferenceManager
        mgr = CoffinInterferenceManager()

        # First request should succeed
        assert mgr.request_frequency("BENCH-001", 76.1) is True
        assert mgr.is_frequency_available(76.1) is False

        # Second request for same freq from different bench should fail
        assert mgr.request_frequency("BENCH-002", 76.1) is False

        # Different freq should succeed
        assert mgr.request_frequency("BENCH-002", 77.0) is True

        # Release and retry
        mgr.release_frequency("BENCH-001")
        assert mgr.is_frequency_available(76.1) is True
        assert mgr.request_frequency("BENCH-002", 76.1) is True


# ===========================================================================
# LLDP Actions Tests
# ===========================================================================


class TestLLDPActions:
    """Tests for LLDP action functions."""

    def test_enable_lldp(self):
        from src.actions.lldp_actions import enable_lldp
        driver = MockRadarDriver()
        enable_lldp(driver)  # Should not raise

    def test_set_rloc_timeout(self):
        from src.actions.lldp_actions import set_rloc_timeout
        driver = MockRadarDriver()
        set_rloc_timeout(driver, 60)  # Should not raise

    def test_change_physical_location(self):
        from src.actions.lldp_actions import change_physical_location
        driver = MockRadarDriver()
        change_physical_location(driver, "FRONT_RIGHT", wait_time_sec=0)
        assert driver.get_physical_location() == "FRONT_RIGHT"

    def test_change_invalid_location(self):
        from src.actions.lldp_actions import change_physical_location
        driver = MockRadarDriver()
        with pytest.raises(ValueError, match="Invalid location"):
            change_physical_location(driver, "INVALID_LOC", wait_time_sec=0)

    def test_get_current_physical_location(self):
        from src.actions.lldp_actions import get_current_physical_location
        driver = MockRadarDriver()
        loc = get_current_physical_location(driver)
        assert loc == "FRONT_CENTER_BOTTOM"

    def test_get_expected_ip(self):
        from src.actions.lldp_actions import get_expected_ip_for_location
        assert get_expected_ip_for_location("FRONT_RIGHT") == "192.168.101.191"
        assert get_expected_ip_for_location("DEFAULT") == "192.168.101.190"

    def test_verify_location_change(self):
        from src.actions.lldp_actions import verify_lldp_location_change
        driver = MockRadarDriver()
        assert verify_lldp_location_change(driver, "FRONT_CENTER_BOTTOM") is True
        assert verify_lldp_location_change(driver, "FRONT_RIGHT") is False

    def test_move_to_scanning(self):
        from src.actions.lldp_actions import move_to_scanning_mode
        driver = MockRadarDriver()
        move_to_scanning_mode(driver, wait_time_sec=0)
        assert driver.state == "SCANNING"


# ===========================================================================
# Power Actions Tests
# ===========================================================================


class TestPowerActions:
    """Tests for power action functions."""

    def test_power_cycle_radar(self):
        from src.actions.power_actions import power_cycle_radar
        driver = MockRadarDriver()
        driver.connect()
        psu = MockPSUDriver()
        psu.power_on()

        power_cycle_radar(driver, psu, off_wait_sec=0.01, on_wait_sec=0.01)
        # Driver should be disconnected by power_cycle
        assert not driver.is_connected

    def test_ensure_power_on_when_off(self):
        from src.actions.power_actions import ensure_power_on
        psu = MockPSUDriver()
        result = ensure_power_on(psu)
        assert result is True

    def test_ensure_power_on_when_on(self):
        from src.actions.power_actions import ensure_power_on
        psu = MockPSUDriver()
        psu.power_on()
        result = ensure_power_on(psu, expected_voltage=12.0)
        assert result is True

