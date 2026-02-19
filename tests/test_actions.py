"""
Unit Tests for the Atomic Actions Module.

Tests the base action pattern, ActionResult, and individual action classes
independently from hardware fixtures (no conftest fixtures needed).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.actions.base import ActionResult, ActionStatus, AtomicAction
from src.actions.radar_actions import RadarActions
from src.actions.psu_actions import PSUActions
from src.actions.ptp_actions import PTPActions


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


class _SuccessAction(AtomicAction):
    """Test action that always succeeds."""

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        return {"key": "value"}


class _FailingAction(AtomicAction):
    """Test action that always raises an exception."""

    def _execute(self, **kwargs: Any) -> Any:
        raise RuntimeError("Intentional failure")


class _ValidatedAction(AtomicAction):
    """Test action with validation."""

    def _validate(self, **kwargs: Any) -> None:
        if "required_param" not in kwargs:
            raise ValueError("required_param is required")

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        return {"param": kwargs["required_param"]}


# ---------------------------------------------------------------------------
# ActionResult Tests
# ---------------------------------------------------------------------------


class TestActionResult:
    """Tests for the ActionResult dataclass."""

    def test_default_result_is_success(self) -> None:
        """Default ActionResult should have SUCCESS status."""
        result = ActionResult()
        assert result.is_success
        assert not result.is_failure

    def test_failure_result(self) -> None:
        """Failure result properties."""
        result = ActionResult(status=ActionStatus.FAILURE, error="something broke")
        assert result.is_failure
        assert not result.is_success
        assert result.error == "something broke"

    def test_timeout_is_failure(self) -> None:
        """Timeout should be treated as a failure."""
        result = ActionResult(status=ActionStatus.TIMEOUT)
        assert result.is_failure

    def test_error_is_failure(self) -> None:
        """Error should be treated as a failure."""
        result = ActionResult(status=ActionStatus.ERROR)
        assert result.is_failure

    def test_to_dict(self) -> None:
        """Verify serialization to dictionary."""
        result = ActionResult(
            status=ActionStatus.SUCCESS,
            data={"key": "value"},
            message="test",
            duration_ms=42.123456,
            metadata={"bench_id": "b1"},
        )
        d = result.to_dict()

        assert d["status"] == "success"
        assert d["data"]["key"] == "value"
        assert d["message"] == "test"
        assert d["duration_ms"] == 42.123
        assert d["metadata"]["bench_id"] == "b1"
        assert d["error"] is None


# ---------------------------------------------------------------------------
# AtomicAction Base Tests
# ---------------------------------------------------------------------------


class TestAtomicAction:
    """Tests for the AtomicAction base class."""

    def test_successful_action(self) -> None:
        """Test an action that executes successfully."""
        action = _SuccessAction(name="test_success")
        result = action.run()

        assert result.is_success
        assert result.data == {"key": "value"}
        assert result.duration_ms > 0
        assert "completed successfully" in result.message

    def test_failing_action(self) -> None:
        """Test an action that raises an exception."""
        action = _FailingAction(name="test_fail")
        result = action.run()

        assert result.is_failure
        assert result.status == ActionStatus.ERROR
        assert "Intentional failure" in result.error
        assert result.duration_ms > 0

    def test_validation_failure(self) -> None:
        """Test an action with failed validation."""
        action = _ValidatedAction(name="test_validate")
        result = action.run()  # Missing required_param

        assert result.is_failure
        assert "required_param" in result.error

    def test_validation_success(self) -> None:
        """Test an action with successful validation."""
        action = _ValidatedAction(name="test_validate")
        result = action.run(required_param="hello")

        assert result.is_success
        assert result.data["param"] == "hello"

    def test_action_name(self) -> None:
        """Test that action name is correctly stored."""
        action = _SuccessAction(name="my_custom_action")
        assert action.name == "my_custom_action"

    def test_action_timeout_setting(self) -> None:
        """Test custom timeout setting."""
        action = _SuccessAction(name="test", timeout_sec=60.0)
        assert action.timeout_sec == 60.0


# ---------------------------------------------------------------------------
# RadarActions Tests
# ---------------------------------------------------------------------------


class TestRadarActions:
    """Tests for the RadarActions class."""

    def test_initialize(self) -> None:
        """Test radar initialization action."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.initialize()

        assert result.is_success
        assert radar.is_connected
        assert result.data["connection"] == "established"

    def test_shutdown(self) -> None:
        """Test radar shutdown action."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        radar.initialize()
        result = radar.shutdown()

        assert result.is_success
        assert not radar.is_connected

    def test_transmit_data(self) -> None:
        """Test data transmission."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.transmit_data(payload=b"\x01\x02\x03")

        assert result.is_success
        assert result.data["bytes_sent"] == 3

    def test_transmit_invalid_payload(self) -> None:
        """Test that invalid payload type is rejected."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.transmit_data(payload="not_bytes")

        assert result.is_failure

    def test_receive_data(self) -> None:
        """Test data reception."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.receive_data()

        assert result.is_success
        assert result.data["bytes_received"] > 0

    def test_get_status(self) -> None:
        """Test status query."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.get_status()

        assert result.is_success
        assert result.data["operational"] is True
        assert "firmware_version" in result.data

    def test_self_test(self) -> None:
        """Test self-test execution."""
        radar = RadarActions(uut_ip="192.168.1.100", uut_port=5000)
        result = radar.run_self_test()

        assert result.is_success
        assert result.data["self_test_passed"] is True

    def test_init_with_empty_ip_fails(self) -> None:
        """Test that empty IP is rejected during init."""
        radar = RadarActions(uut_ip="", uut_port=5000)
        result = radar.initialize()

        assert result.is_failure


# ---------------------------------------------------------------------------
# PSUActions Tests
# ---------------------------------------------------------------------------


class TestPSUActions:
    """Tests for the PSUActions class."""

    def test_power_on(self) -> None:
        """Test PSU power on."""
        psu = PSUActions(model="TestPSU")
        result = psu.power_on(voltage=12.0, current_limit=3.0)

        assert result.is_success
        assert psu.is_powered_on
        assert psu.current_voltage == 12.0

    def test_power_off(self) -> None:
        """Test PSU power off."""
        psu = PSUActions(model="TestPSU")
        psu.power_on(voltage=12.0, current_limit=3.0)
        result = psu.power_off()

        assert result.is_success
        assert not psu.is_powered_on

    def test_measure(self) -> None:
        """Test PSU measurement readback."""
        psu = PSUActions(model="TestPSU")
        result = psu.measure()

        assert result.is_success
        assert "voltage_measured" in result.data
        assert "current_measured" in result.data

    def test_set_voltage(self) -> None:
        """Test voltage adjustment."""
        psu = PSUActions(model="TestPSU")
        result = psu.set_voltage(voltage=24.0)

        assert result.is_success
        assert psu.current_voltage == 24.0

    def test_reject_zero_voltage(self) -> None:
        """Test that zero voltage is rejected."""
        psu = PSUActions(model="TestPSU")
        result = psu.power_on(voltage=0, current_limit=3.0)

        assert result.is_failure


# ---------------------------------------------------------------------------
# PTPActions Tests
# ---------------------------------------------------------------------------


class TestPTPActions:
    """Tests for the PTPActions class."""

    def test_start_sync(self) -> None:
        """Test PTP sync start."""
        ptp = PTPActions(master_ip="192.168.1.1", domain=0)
        result = ptp.start_sync()

        assert result.is_success
        assert ptp.is_synced
        assert result.data["sync_state"] == "synchronized"

    def test_stop_sync(self) -> None:
        """Test PTP sync stop."""
        ptp = PTPActions(master_ip="192.168.1.1")
        ptp.start_sync()
        result = ptp.stop_sync()

        assert result.is_success
        assert not ptp.is_synced

    def test_get_sync_status(self) -> None:
        """Test PTP status query."""
        ptp = PTPActions(master_ip="192.168.1.1")
        result = ptp.get_sync_status()

        assert result.is_success
        assert "offset_us" in result.data

    def test_validate_accuracy(self) -> None:
        """Test PTP accuracy validation."""
        ptp = PTPActions(master_ip="192.168.1.1")
        result = ptp.validate_accuracy(max_offset_us=1.0)

        assert result.is_success
        assert result.data["within_threshold"] is True

    def test_start_sync_empty_ip_fails(self) -> None:
        """Test that empty master IP is rejected."""
        ptp = PTPActions(master_ip="")
        result = ptp.start_sync()

        assert result.is_failure

