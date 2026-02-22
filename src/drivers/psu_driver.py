"""
PSU Driver — Keysight E36233A Dual Output DC Power Supply control.

The PSU sits at a fixed IP (192.168.10.3) behind a dumb switch shared
by two host PCs. A file-based lock prevents command collisions.

Features:
- Dual output control (each port for a different radar)
- Collision avoidance via file lock (two hosts share one Ethernet)
- 12V / 10A output configuration for radar operation
- Mock mode for testing without hardware
"""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Generator, Optional

from loguru import logger


@dataclass
class PSUMeasurement:
    """PSU measurement result."""
    voltage_v: float = 0.0
    current_a: float = 0.0
    power_w: float = 0.0
    output_enabled: bool = False
    port: int = 1


@dataclass
class PSUConfig:
    """PSU configuration parameters."""
    ip: str = "192.168.10.3"
    scpi_port: int = 5025
    port: int = 1  # Output port (1 or 2)
    voltage_v: float = 12.0
    current_limit_a: float = 10.0
    lock_file_dir: str = ""  # Directory for lock files
    lock_timeout_sec: int = 30
    simulate: bool = False


class PSUFileLock:
    """
    Simple file-based lock to prevent PSU command collisions.

    Two hosts share one Ethernet connection to the PSU through a dumb switch.
    This lock ensures only one host sends SCPI commands at a time.
    """

    def __init__(self, lock_dir: str, psu_ip: str, timeout_sec: int = 30) -> None:
        self.lock_dir = lock_dir or os.path.join(os.path.expanduser("~"), ".psu_locks")
        os.makedirs(self.lock_dir, exist_ok=True)
        safe_ip = psu_ip.replace(".", "_")
        self.lock_file = os.path.join(self.lock_dir, f"psu_{safe_ip}.lock")
        self.timeout_sec = timeout_sec
        self._fd = None

    def acquire(self) -> bool:
        """Acquire the PSU lock. Returns True if acquired."""
        start = time.time()
        while (time.time() - start) < self.timeout_sec:
            try:
                self._fd = os.open(
                    self.lock_file,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, f"{os.getpid()}\n".encode())
                logger.debug(f"PSUFileLock: Acquired lock {self.lock_file}")
                return True
            except FileExistsError:
                # Check if the holding process is still alive (stale lock)
                if self._is_stale():
                    self._force_release()
                    continue
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"PSUFileLock: Error acquiring lock: {e}")
                time.sleep(1)
        logger.error(f"PSUFileLock: Timeout acquiring lock after {self.timeout_sec}s")
        return False

    def release(self) -> None:
        """Release the PSU lock."""
        try:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
                logger.debug(f"PSUFileLock: Released lock {self.lock_file}")
        except Exception as e:
            logger.warning(f"PSUFileLock: Error releasing lock: {e}")

    def _is_stale(self) -> bool:
        """Check if an existing lock file is from a dead process."""
        try:
            with open(self.lock_file, "r") as f:
                pid_str = f.read().strip()
            if not pid_str:
                return True
            pid = int(pid_str)
            # Check if process is still running
            try:
                os.kill(pid, 0)
                return False  # Process is alive
            except (ProcessLookupError, PermissionError):
                return True  # Process is dead
        except Exception:
            return True

    def _force_release(self) -> None:
        """Force-release a stale lock."""
        try:
            os.remove(self.lock_file)
            logger.warning(f"PSUFileLock: Force-released stale lock {self.lock_file}")
        except Exception:
            pass


class PSUDriver:
    """
    Driver for Keysight E36233A Dual Output DC Power Supply.

    Uses SCPI commands over TCP/IP to control the PSU.
    Includes file-based locking for shared Ethernet access.
    """

    # Keysight E36233A specs
    MAX_VOLTAGE = 30.0
    MAX_CURRENT = 20.0
    DEFAULT_RADAR_VOLTAGE = 12.0
    DEFAULT_RADAR_CURRENT_LIMIT = 10.0

    def __init__(self, config: PSUConfig) -> None:
        self.config = config
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._lock = PSUFileLock(
            config.lock_file_dir,
            config.ip,
            config.lock_timeout_sec,
        )
        self._simulate = config.simulate
        logger.info(
            f"PSUDriver initialized — IP={config.ip}, Port={config.port}, "
            f"Simulate={config.simulate}"
        )

    @contextmanager
    def _scpi_session(self) -> Generator[None, None, None]:
        """
        Context manager for SCPI communication with PSU lock.
        Acquires the file lock, opens socket, yields, then cleans up.
        """
        if self._simulate:
            yield
            return

        if not self._lock.acquire():
            raise TimeoutError(
                f"Could not acquire PSU lock for {self.config.ip} "
                f"within {self.config.lock_timeout_sec}s"
            )
        try:
            self._open_socket()
            yield
        finally:
            self._close_socket()
            self._lock.release()

    def _open_socket(self) -> None:
        """Open TCP socket to PSU."""
        if self._simulate:
            return
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(10)
            self._socket.connect((self.config.ip, self.config.scpi_port))
            self._connected = True
            logger.debug(f"PSU socket connected to {self.config.ip}:{self.config.scpi_port}")
        except Exception as e:
            logger.error(f"PSU socket connection failed: {e}")
            raise

    def _close_socket(self) -> None:
        """Close TCP socket."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
            self._connected = False

    def _send_scpi(self, command: str) -> str:
        """Send a SCPI command and return the response (if query)."""
        if self._simulate:
            return self._mock_scpi_response(command)

        if not self._socket:
            raise ConnectionError("PSU socket not connected")

        cmd_bytes = (command.strip() + "\n").encode()
        self._socket.sendall(cmd_bytes)
        logger.debug(f"PSU SCPI >> {command.strip()}")

        if "?" in command:
            response = self._socket.recv(4096).decode().strip()
            logger.debug(f"PSU SCPI << {response}")
            return response
        return ""

    def _mock_scpi_response(self, command: str) -> str:
        """Generate mock SCPI responses for simulation mode."""
        cmd = command.strip().upper()
        if "*IDN?" in cmd:
            return "Keysight Technologies,E36233A,MY12345678,1.0.0"
        if "MEAS:VOLT?" in cmd:
            return "12.010"
        if "MEAS:CURR?" in cmd:
            return "2.350"
        if "OUTP?" in cmd:
            return "1"
        if "VOLT?" in cmd:
            return "12.000"
        if "CURR?" in cmd:
            return "10.000"
        if "SYST:ERR?" in cmd:
            return '0,"No error"'
        return ""

    @property
    def channel_prefix(self) -> str:
        """SCPI channel selector prefix for the configured port."""
        return f"(@{self.config.port})"

    def identify(self) -> str:
        """Query PSU identity (*IDN?)."""
        with self._scpi_session():
            return self._send_scpi("*IDN?")

    def power_on(self) -> bool:
        """
        Enable output on the configured port with safe voltage/current.

        Sequence:
        1. Set voltage to configured value (default 12V)
        2. Set current limit (default 10A)
        3. Enable output
        """
        logger.info(f"PSU: Powering ON port {self.config.port} "
                     f"({self.config.voltage_v}V / {self.config.current_limit_a}A)")
        with self._scpi_session():
            ch = self.channel_prefix
            self._send_scpi(f"VOLT {self.config.voltage_v},{ch}")
            self._send_scpi(f"CURR {self.config.current_limit_a},{ch}")
            self._send_scpi(f"OUTP ON,{ch}")

            # Verify
            time.sleep(0.2)
            state = self._send_scpi(f"OUTP? {ch}")
            if state.strip() in ("1", "ON"):
                logger.info(f"PSU: Port {self.config.port} is ON")
                return True
            logger.error(f"PSU: Port {self.config.port} failed to turn ON, got: {state}")
            return False

    def power_off(self) -> bool:
        """Disable output on the configured port."""
        logger.info(f"PSU: Powering OFF port {self.config.port}")
        with self._scpi_session():
            ch = self.channel_prefix
            self._send_scpi(f"OUTP OFF,{ch}")

            time.sleep(0.2)
            state = self._send_scpi(f"OUTP? {ch}")
            if state.strip() in ("0", "OFF"):
                logger.info(f"PSU: Port {self.config.port} is OFF")
                return True
            logger.error(f"PSU: Port {self.config.port} failed to turn OFF")
            return False

    def measure(self) -> PSUMeasurement:
        """Measure voltage, current, and power on the configured port."""
        with self._scpi_session():
            ch = self.channel_prefix
            voltage = float(self._send_scpi(f"MEAS:VOLT? {ch}"))
            current = float(self._send_scpi(f"MEAS:CURR? {ch}"))
            state = self._send_scpi(f"OUTP? {ch}")
            return PSUMeasurement(
                voltage_v=voltage,
                current_a=current,
                power_w=round(voltage * current, 3),
                output_enabled=state.strip() in ("1", "ON"),
                port=self.config.port,
            )

    def set_voltage(self, voltage_v: float) -> bool:
        """Set output voltage (with safety check)."""
        if voltage_v > self.MAX_VOLTAGE or voltage_v < 0:
            logger.error(f"PSU: Voltage {voltage_v}V out of range [0, {self.MAX_VOLTAGE}]")
            return False
        with self._scpi_session():
            self._send_scpi(f"VOLT {voltage_v},{self.channel_prefix}")
            return True

    def set_current_limit(self, current_a: float) -> bool:
        """Set output current limit (with safety check)."""
        if current_a > self.MAX_CURRENT or current_a < 0:
            logger.error(f"PSU: Current {current_a}A out of range [0, {self.MAX_CURRENT}]")
            return False
        with self._scpi_session():
            self._send_scpi(f"CURR {current_a},{self.channel_prefix}")
            return True

    def check_errors(self) -> str:
        """Query system error queue."""
        with self._scpi_session():
            return self._send_scpi("SYST:ERR?")

    def power_cycle(self, off_duration_sec: float = 5.0) -> bool:
        """
        Power cycle the radar: OFF → wait → ON.
        Used in LLDP and reset scenarios.
        """
        logger.info(f"PSU: Power cycling port {self.config.port} "
                     f"(off for {off_duration_sec}s)")
        if not self.power_off():
            return False
        time.sleep(off_duration_sec)
        return self.power_on()


class MockPSUDriver(PSUDriver):
    """
    Mock PSU driver for testing without hardware.
    Overrides all SCPI communication to use simulation.
    """

    def __init__(self, config: Optional[PSUConfig] = None) -> None:
        if config is None:
            config = PSUConfig(simulate=True)
        else:
            config.simulate = True
        super().__init__(config)
        self._output_on = False
        self._voltage_set = config.voltage_v
        self._current_set = config.current_limit_a

    def power_on(self) -> bool:
        logger.info(f"MockPSU: Port {self.config.port} ON ({self._voltage_set}V / {self._current_set}A)")
        self._output_on = True
        return True

    def power_off(self) -> bool:
        logger.info(f"MockPSU: Port {self.config.port} OFF")
        self._output_on = False
        return True

    def measure(self) -> PSUMeasurement:
        voltage = self._voltage_set if self._output_on else 0.0
        current = 2.35 if self._output_on else 0.0
        return PSUMeasurement(
            voltage_v=voltage,
            current_a=current,
            power_w=round(voltage * current, 3),
            output_enabled=self._output_on,
            port=self.config.port,
        )

    def set_voltage(self, voltage_v: float) -> bool:
        if voltage_v > self.MAX_VOLTAGE or voltage_v < 0:
            return False
        self._voltage_set = voltage_v
        return True

    def set_current_limit(self, current_a: float) -> bool:
        if current_a > self.MAX_CURRENT or current_a < 0:
            return False
        self._current_set = current_a
        return True

    def identify(self) -> str:
        return "Mock Keysight E36233A"

    def check_errors(self) -> str:
        return '0,"No error"'

    def power_cycle(self, off_duration_sec: float = 5.0) -> bool:
        logger.info(f"MockPSU: Power cycle port {self.config.port} (off={off_duration_sec}s)")
        self._output_on = False
        time.sleep(min(off_duration_sec, 0.1))  # Short wait in mock
        self._output_on = True
        return True

