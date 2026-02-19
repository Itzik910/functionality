"""
PSU (Power Supply Unit) Atomic Actions.

Encapsulates atomic operations for the software-controlled PSU:
- Power on/off control.
- Voltage and current configuration.
- Measurement readback.
- Safety limit monitoring.

Design Reference: Section 1 — "PSU: Software-controlled, providing power to the radar."
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from src.actions.base import ActionResult, AtomicAction


class PSUActions:
    """
    Collection of atomic actions for Power Supply Unit operations.

    Provides a high-level API for PSU control. In the initial PoC,
    all hardware interactions are mocked. Real implementations will
    use serial/SCPI communication with the physical PSU.

    Usage::

        psu = PSUActions(interface="serial", port="COM3")
        result = psu.power_on(voltage=12.0, current_limit=3.0)
        assert result.is_success
    """

    def __init__(
        self,
        interface: str = "serial",
        port: Optional[str] = None,
        ip_address: Optional[str] = None,
        model: str = "MockPSU",
    ) -> None:
        """
        Initialize the PSU actions interface.

        Args:
            interface: Communication interface ("serial", "ethernet", "usb", "gpib").
            port: Serial/COM port (if serial interface).
            ip_address: PSU IP address (if ethernet interface).
            model: PSU model identifier.
        """
        self.interface = interface
        self.port = port
        self.ip_address = ip_address
        self.model = model
        self._powered_on = False
        self._voltage = 0.0
        self._current_limit = 0.0
        logger.info(f"PSUActions initialized — model={model}, interface={interface}")

    def power_on(self, voltage: float, current_limit: float, **kwargs: Any) -> ActionResult:
        """Power on the PSU with specified voltage and current limit."""
        action = _PowerOnAction(
            model=self.model,
            interface=self.interface,
        )
        result = action.run(voltage=voltage, current_limit=current_limit, **kwargs)
        if result.is_success:
            self._powered_on = True
            self._voltage = voltage
            self._current_limit = current_limit
        return result

    def power_off(self, **kwargs: Any) -> ActionResult:
        """Power off the PSU."""
        action = _PowerOffAction(model=self.model)
        result = action.run(**kwargs)
        if result.is_success:
            self._powered_on = False
            self._voltage = 0.0
        return result

    def set_voltage(self, voltage: float, **kwargs: Any) -> ActionResult:
        """Set the output voltage."""
        action = _SetVoltageAction(model=self.model)
        result = action.run(voltage=voltage, **kwargs)
        if result.is_success:
            self._voltage = voltage
        return result

    def measure(self, **kwargs: Any) -> ActionResult:
        """Read current voltage and current measurements from the PSU."""
        action = _MeasureAction(model=self.model)
        return action.run(**kwargs)

    @property
    def is_powered_on(self) -> bool:
        """Check if the PSU output is currently enabled."""
        return self._powered_on

    @property
    def current_voltage(self) -> float:
        """Get the currently set voltage."""
        return self._voltage


# ---------------------------------------------------------------------------
# Internal Atomic Action Implementations
# ---------------------------------------------------------------------------


class _PowerOnAction(AtomicAction):
    """Atomic action: Power on PSU with given parameters."""

    def __init__(self, model: str, interface: str) -> None:
        super().__init__(name="psu_power_on", timeout_sec=10.0)
        self.model = model
        self.interface = interface

    def _validate(self, **kwargs: Any) -> None:
        voltage = kwargs.get("voltage", 0)
        current_limit = kwargs.get("current_limit", 0)
        if voltage <= 0:
            raise ValueError(f"Voltage must be positive, got {voltage}")
        if current_limit <= 0:
            raise ValueError(f"Current limit must be positive, got {current_limit}")

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        voltage = kwargs["voltage"]
        current_limit = kwargs["current_limit"]
        logger.info(
            f"PSU [{self.model}] Power ON — V={voltage}V, I_max={current_limit}A"
        )
        # TODO: Replace with actual SCPI/serial command
        # e.g., psu.write(f"VOLT {voltage}; CURR {current_limit}; OUTP ON")
        return {
            "output": "enabled",
            "voltage_set": voltage,
            "current_limit_set": current_limit,
            "model": self.model,
        }


class _PowerOffAction(AtomicAction):
    """Atomic action: Power off PSU."""

    def __init__(self, model: str) -> None:
        super().__init__(name="psu_power_off", timeout_sec=5.0)
        self.model = model

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        logger.info(f"PSU [{self.model}] Power OFF")
        # TODO: Replace with actual SCPI command: psu.write("OUTP OFF")
        return {"output": "disabled", "model": self.model}


class _SetVoltageAction(AtomicAction):
    """Atomic action: Set PSU output voltage."""

    def __init__(self, model: str) -> None:
        super().__init__(name="psu_set_voltage", timeout_sec=5.0)
        self.model = model

    def _validate(self, **kwargs: Any) -> None:
        voltage = kwargs.get("voltage", 0)
        if voltage < 0:
            raise ValueError(f"Voltage cannot be negative, got {voltage}")

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        voltage = kwargs["voltage"]
        logger.info(f"PSU [{self.model}] Set voltage to {voltage}V")
        # TODO: Replace with actual SCPI command
        return {"voltage_set": voltage, "model": self.model}


class _MeasureAction(AtomicAction):
    """Atomic action: Read PSU measurements."""

    def __init__(self, model: str) -> None:
        super().__init__(name="psu_measure", timeout_sec=5.0)
        self.model = model

    def _execute(self, **kwargs: Any) -> Dict[str, Any]:
        logger.info(f"PSU [{self.model}] Reading measurements")
        # TODO: Replace with actual SCPI queries
        # e.g., voltage = psu.query("MEAS:VOLT?")
        #        current = psu.query("MEAS:CURR?")
        return {
            "voltage_measured": 12.01,
            "current_measured": 1.85,
            "power_watts": 22.22,
            "model": self.model,
        }

