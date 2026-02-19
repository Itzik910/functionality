"""
Functional Tests — PSU Operations.

Tests Power Supply Unit operations using atomic actions:
- Power on/off control.
- Voltage configuration.
- Measurement readback.

Demonstrates PSU fixture usage and threshold validation.
"""

from __future__ import annotations

import pytest

from src.actions.base import ActionStatus


@pytest.mark.functional
@pytest.mark.xray("RADAR-201")
class TestPSUPowerControl:
    """Tests for PSU power on/off operations."""

    def test_psu_power_on(self, psu) -> None:
        """Verify PSU can be powered on with valid parameters."""
        result = psu.power_on(voltage=12.0, current_limit=3.0)

        assert result.is_success, f"PSU power on failed: {result.error}"
        assert result.data["output"] == "enabled"
        assert result.data["voltage_set"] == 12.0
        assert psu.is_powered_on

    def test_psu_power_off(self, psu) -> None:
        """Verify PSU can be powered off safely."""
        # Ensure it's on first
        psu.power_on(voltage=12.0, current_limit=3.0)

        result = psu.power_off()

        assert result.is_success, f"PSU power off failed: {result.error}"
        assert result.data["output"] == "disabled"
        assert not psu.is_powered_on

    def test_psu_rejects_invalid_voltage(self, psu) -> None:
        """Verify PSU rejects negative/zero voltage."""
        result = psu.power_on(voltage=0, current_limit=3.0)

        assert result.is_failure, "Should reject zero voltage"
        assert result.status == ActionStatus.ERROR

    def test_psu_rejects_invalid_current(self, psu) -> None:
        """Verify PSU rejects negative/zero current limit."""
        result = psu.power_on(voltage=12.0, current_limit=0)

        assert result.is_failure, "Should reject zero current limit"
        assert result.status == ActionStatus.ERROR


@pytest.mark.functional
@pytest.mark.xray("RADAR-202")
class TestPSUMeasurements:
    """Tests for PSU measurement readback."""

    def test_psu_measure_returns_values(self, psu) -> None:
        """Verify PSU measurement returns voltage, current, and power."""
        result = psu.measure()

        assert result.is_success, f"PSU measure failed: {result.error}"
        assert "voltage_measured" in result.data
        assert "current_measured" in result.data
        assert "power_watts" in result.data

    def test_psu_power_within_threshold(self, psu, thresholds) -> None:
        """Verify PSU power consumption is within configured thresholds."""
        result = psu.measure()

        assert result.is_success
        power_threshold = thresholds.get("power_consumption", {})
        max_watts = power_threshold.get("max_watts", 120.0)

        assert result.data["power_watts"] <= max_watts, (
            f"Power consumption {result.data['power_watts']}W "
            f"exceeds threshold {max_watts}W"
        )

    def test_psu_set_voltage(self, psu) -> None:
        """Verify voltage can be changed dynamically."""
        result = psu.set_voltage(voltage=24.0)

        assert result.is_success, f"Set voltage failed: {result.error}"
        assert result.data["voltage_set"] == 24.0
        assert psu.current_voltage == 24.0

