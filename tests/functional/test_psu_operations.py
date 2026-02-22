"""
Functional Tests — PSU Operations.

Tests Power Supply Unit (Keysight E36233A) operations:
- Power on/off control.
- Voltage and current configuration.
- Measurement readback.
- Power cycling.

Uses the psu_control fixture from conftest.py which provides
a PSUDriver instance (real or Mock depending on configuration).
"""

from __future__ import annotations

import pytest

from src.drivers.psu_driver import PSUMeasurement


@pytest.mark.functional
@pytest.mark.xray("RADAR-201")
class TestPSUPowerControl:
    """Tests for PSU power on/off operations."""

    def test_psu_power_on(self, psu_control) -> None:
        """Verify PSU can be powered on."""
        assert psu_control.power_on() is True

    def test_psu_power_off(self, psu_control) -> None:
        """Verify PSU can be powered off safely."""
        psu_control.power_on()
        assert psu_control.power_off() is True

    def test_psu_set_voltage_valid(self, psu_control) -> None:
        """Verify voltage can be set within valid range."""
        assert psu_control.set_voltage(12.0) is True

    def test_psu_set_voltage_invalid_high(self, psu_control) -> None:
        """Verify PSU rejects voltage above maximum."""
        assert psu_control.set_voltage(35.0) is False

    def test_psu_set_voltage_invalid_negative(self, psu_control) -> None:
        """Verify PSU rejects negative voltage."""
        assert psu_control.set_voltage(-1.0) is False

    def test_psu_set_current_valid(self, psu_control) -> None:
        """Verify current limit can be set within valid range."""
        assert psu_control.set_current_limit(10.0) is True

    def test_psu_set_current_invalid(self, psu_control) -> None:
        """Verify PSU rejects current above maximum."""
        assert psu_control.set_current_limit(25.0) is False


@pytest.mark.functional
@pytest.mark.xray("RADAR-202")
class TestPSUMeasurements:
    """Tests for PSU measurement readback."""

    def test_psu_measure_returns_values(self, psu_control) -> None:
        """Verify PSU measurement returns voltage, current, and power."""
        psu_control.power_on()
        meas = psu_control.measure()
        assert isinstance(meas, PSUMeasurement)
        assert meas.voltage_v >= 0
        assert meas.current_a >= 0
        assert meas.power_w >= 0

    def test_psu_measure_when_on(self, psu_control) -> None:
        """Verify PSU reports non-zero voltage when output is on."""
        psu_control.power_on()
        meas = psu_control.measure()
        assert meas.output_enabled is True
        assert meas.voltage_v > 0

    def test_psu_power_within_threshold(self, psu_control, thresholds) -> None:
        """Verify PSU power consumption is within configured thresholds."""
        psu_control.power_on()
        meas = psu_control.measure()
        power_threshold = thresholds.get("power_consumption", {})
        max_watts = power_threshold.get("max_watts", 120.0)
        assert meas.power_w <= max_watts, (
            f"Power consumption {meas.power_w}W exceeds threshold {max_watts}W"
        )

    def test_psu_identify(self, psu_control) -> None:
        """Verify PSU identification."""
        idn = psu_control.identify()
        assert "E36233A" in idn


@pytest.mark.functional
@pytest.mark.xray("RADAR-203")
class TestPSUPowerCycle:
    """Tests for PSU power cycling."""

    def test_power_cycle(self, psu_control) -> None:
        """Verify PSU can perform a power cycle."""
        psu_control.power_on()
        assert psu_control.power_cycle(off_duration_sec=0.01) is True
