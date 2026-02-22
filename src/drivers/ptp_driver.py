"""
PTP (Precision Time Protocol) Driver — manages ptp4l process.

Configures and controls ptp4l for PTP synchronization between the
Host PC and radar. In production, runs as a subprocess with sudo.

PTP configuration (ptp.txt):
    [global]
    domainNumber 1
    network_transport L2
    logSyncInterval -4
    logAnnounceInterval -2
    logMinDelayReqInterval -2

Command:
    echo "$password" | sudo -S ptp4l -f ptp.txt -E2 -m -H -l 6 -i $eth

Note: In the future, this will transition to gPTP and the command
structure will need to change accordingly.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class PTPStatus:
    """PTP synchronization status."""
    running: bool = False
    synced: bool = False
    offset_ns: float = 0.0
    delay_ns: float = 0.0
    state: str = "UNKNOWN"  # LISTENING, UNCALIBRATED, SLAVE, MASTER
    clock_id: str = ""
    port_state: str = ""
    uptime_sec: int = 0


@dataclass
class PTPConfig:
    """PTP configuration parameters."""
    interface: str = "eth0"
    domain: int = 1
    network_transport: str = "L2"
    log_sync_interval: int = -4
    log_announce_interval: int = -2
    log_min_delay_req_interval: int = -2
    password: str = "trio_012"
    config_file: str = "ptp.txt"
    sync_timeout_sec: int = 30
    simulate: bool = False


class PTPDriver:
    """
    Manages ptp4l process for PTP time synchronization.

    In production:
    - Generates ptp.txt configuration file
    - Starts ptp4l as a background subprocess with sudo
    - Monitors synchronization state
    - Stops the process cleanly

    In simulation mode, all operations are mocked.
    """

    def __init__(self, config: PTPConfig) -> None:
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._synced = False
        self._start_time = 0.0
        self._simulate = config.simulate
        logger.info(
            f"PTPDriver initialized — interface={config.interface}, "
            f"domain={config.domain}, simulate={config.simulate}"
        )

    def _generate_config_file(self) -> str:
        """Generate ptp.txt configuration file and return its path."""
        config_content = (
            "[global]\n"
            f"domainNumber {self.config.domain}\n"
            f"network_transport {self.config.network_transport}\n"
            f"logSyncInterval {self.config.log_sync_interval}\n"
            f"logAnnounceInterval {self.config.log_announce_interval}\n"
            f"logMinDelayReqInterval {self.config.log_min_delay_req_interval}\n"
        )
        config_path = os.path.abspath(self.config.config_file)
        with open(config_path, "w") as f:
            f.write(config_content)
        logger.info(f"PTP config file written: {config_path}")
        return config_path

    def start(self) -> bool:
        """
        Start ptp4l synchronization.

        Command:
            echo "$password" | sudo -S ptp4l -f ptp.txt -E2 -m -H -l 6 -i $eth
        """
        if self._running:
            logger.warning("PTPDriver: ptp4l already running")
            return True

        if self._simulate:
            self._running = True
            self._synced = True
            self._start_time = time.time()
            logger.info("PTPDriver [MOCK]: ptp4l started (simulation)")
            return True

        try:
            config_path = self._generate_config_file()
            cmd = (
                f'echo "{self.config.password}" | sudo -S '
                f'ptp4l -f {config_path} -E2 -m -H -l 6 -i {self.config.interface}'
            )
            logger.info(f"PTPDriver: Starting ptp4l on {self.config.interface}")
            self._process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._running = True
            self._start_time = time.time()

            # Wait for synchronization
            if self._wait_for_sync():
                self._synced = True
                logger.info("PTPDriver: ptp4l synchronized successfully")
                return True
            else:
                logger.error("PTPDriver: ptp4l failed to synchronize within timeout")
                return False

        except Exception as e:
            logger.error(f"PTPDriver: Failed to start ptp4l: {e}")
            return False

    def stop(self) -> bool:
        """Stop ptp4l process."""
        if self._simulate:
            self._running = False
            self._synced = False
            logger.info("PTPDriver [MOCK]: ptp4l stopped (simulation)")
            return True

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
                logger.info("PTPDriver: ptp4l stopped")
            except subprocess.TimeoutExpired:
                self._process.kill()
                logger.warning("PTPDriver: ptp4l force-killed")
            except Exception as e:
                logger.error(f"PTPDriver: Error stopping ptp4l: {e}")
                return False
            finally:
                self._process = None
        self._running = False
        self._synced = False
        return True

    def get_status(self) -> PTPStatus:
        """Get current PTP synchronization status."""
        if self._simulate:
            return PTPStatus(
                running=self._running,
                synced=self._synced,
                offset_ns=12.5 if self._synced else 0.0,
                delay_ns=250.0 if self._synced else 0.0,
                state="SLAVE" if self._synced else "LISTENING",
                uptime_sec=int(time.time() - self._start_time) if self._running else 0,
            )

        if not self._running or not self._process:
            return PTPStatus(running=False)

        # In a real implementation, we'd parse ptp4l output
        return PTPStatus(
            running=self._process.poll() is None,
            synced=self._synced,
            state="SLAVE" if self._synced else "LISTENING",
            uptime_sec=int(time.time() - self._start_time),
        )

    def _wait_for_sync(self) -> bool:
        """Wait for ptp4l to reach SLAVE state."""
        start = time.time()
        while (time.time() - start) < self.config.sync_timeout_sec:
            if self._process and self._process.poll() is not None:
                logger.error("PTPDriver: ptp4l process terminated unexpectedly")
                return False
            # In real implementation: parse ptp4l stdout for "SLAVE" state
            time.sleep(1)
        return False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_synced(self) -> bool:
        return self._synced

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

