"""
Mock Radar Driver — simulation layer for testing without hardware.

Provides realistic mock responses for all radar operations, allowing
the entire test framework to run in simulation mode. This enables:
- CI/CD pipeline validation
- Test logic development without hardware
- Integration testing of the framework itself
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.drivers.radar_driver_base import (
    ConnectResponse,
    ConnectStatus,
    DetectionData,
    HeartbeatData,
    PointCloudFrame,
    RadarDriverBase,
    StatisticsData,
)


class MockRadarDriver(RadarDriverBase):
    """
    Mock radar driver that simulates BSR/HRR radar behavior.

    Generates realistic mock data for all radar operations including
    heartbeat, point cloud / SODA frames, and statistics.
    """

    def __init__(
        self,
        ip: str = "192.168.101.190",
        radar_type: str = "BSR32",
        is_hrr: bool = False,
        password: Optional[str] = None,
        fail_connect: bool = False,
        fail_ping: bool = False,
    ) -> None:
        super().__init__(ip=ip, radar_type=radar_type, is_hrr=is_hrr, password=password)
        self._fail_connect = fail_connect
        self._fail_ping = fail_ping
        self._fw_version = "v5.4.1-0-ge7cdd756" if not is_hrr else "v4.6.5-40-gb2c16779"
        self._state = "STANDBY"
        self._location = "FRONT_CENTER_BOTTOM"
        self._lldp_enabled = False
        self._rloc_timeout = 0
        self._recording = False
        self._beat_counter = 0
        self._cycle_counter = 0
        self._start_time = time.time()
        logger.info(f"MockRadarDriver [{radar_type}] initialized — simulation mode at {ip}")

    def connect(self, ping_timeout: int = 10) -> ConnectResponse:
        if self._fail_connect:
            logger.warning(f"MockDriver: Simulating connection failure to {self.ip}")
            return ConnectResponse(
                status=ConnectStatus.NO_PING,
                message="Simulated connection failure",
            )
        self._connected = True
        self._state = "STANDBY"
        logger.info(f"MockDriver: Connected to {self.radar_type} at {self.ip}")
        return ConnectResponse(
            status=ConnectStatus.OK,
            message="Mock connection established",
            fw_version=self._fw_version,
            sensor_id=f"MOCK-{self.radar_type}-001",
            physical_location=self._location,
        )

    def disconnect(self) -> None:
        self._connected = False
        self._recording = False
        logger.info(f"MockDriver: Disconnected from {self.ip}")

    def ping(self, timeout: int = 5) -> bool:
        if self._fail_ping:
            return False
        return True

    def get_heartbeat(self, timeout: int = 5) -> Optional[HeartbeatData]:
        if not self._connected:
            return None
        self._beat_counter += 1
        now = time.time()
        return HeartbeatData(
            beat_id=self._beat_counter,
            status="OK",
            timestamp_sec=int(now),
            timestamp_nsec=int((now % 1) * 1e9),
            sensor_id=f"MOCK-{self.radar_type}-001",
            sensor_type=self.radar_type,
            fw_version=self._fw_version,
            temperatures={
                "tsip_0": round(random.uniform(35.0, 50.0), 1),
                "tsip_1": round(random.uniform(35.0, 50.0), 1),
            },
            voltages={
                "main": 12.01,
                "rfic_1": 1.20,
            },
            error_counters={
                "frame_time": 0,
                "crc": 0,
            },
            uptime_sec=int(now - self._start_time),
        )

    def get_point_cloud(self, timeout: int = 5) -> Optional[PointCloudFrame]:
        if not self._connected:
            return None
        self._cycle_counter += 1
        num_detections = random.randint(5, 50)
        detections: List[DetectionData] = []
        for _ in range(num_detections):
            dist = random.uniform(1.0, 200.0)
            azi = random.uniform(-1.0, 1.0)
            elev = random.uniform(-0.3, 0.3)
            import math
            x = dist * math.cos(azi) * math.cos(elev)
            y = dist * math.sin(azi) * math.cos(elev)
            z = dist * math.sin(elev)
            detections.append(DetectionData(
                distance=round(dist, 3),
                azimuth=round(azi, 4),
                elevation=round(elev, 4),
                velocity=round(random.uniform(-30.0, 30.0), 2),
                rcs=round(random.uniform(-10.0, 30.0), 1),
                x=round(x, 2),
                y=round(y, 2),
                z=round(z, 2),
            ))
        now = time.time()
        return PointCloudFrame(
            cycle_count=self._cycle_counter,
            timestamp_sec=int(now),
            timestamp_nsec=int((now % 1) * 1e9),
            valid_detections=num_detections,
            detections=detections,
            latency_ms=round(random.uniform(5.0, 25.0), 2),
        )

    def get_statistics(self) -> StatisticsData:
        return StatisticsData(
            fps_current=round(random.uniform(9.5, 10.5), 1),
            fps_mean=10.0,
            fps_min=9.2,
            fps_max=10.8,
            latency_current_ms=round(random.uniform(8.0, 15.0), 2),
            latency_mean_ms=11.5,
            drops_counters={"soda": 0, "heartbeat": 0},
            sync_loss_counter=0,
            temperatures={
                "tsip_0_current": round(random.uniform(35.0, 50.0), 1),
            },
        )

    def update_fw(self, modality: Optional[str] = None, force: bool = False) -> bool:
        logger.info(f"MockDriver: Simulating FW update (modality={modality}, force={force})")
        time.sleep(0.1)  # Simulate brief delay
        return True

    def reset(self, reset_type: str = "COLD") -> bool:
        logger.info(f"MockDriver: Simulating {reset_type} reset")
        self._state = "STANDBY"
        self._cycle_counter = 0
        return True

    def set_state(self, state: str) -> bool:
        valid_states = ["STANDBY", "SCANNING", "FW_UPDATE"]
        if state not in valid_states:
            logger.error(f"MockDriver: Invalid state '{state}'. Valid: {valid_states}")
            return False
        self._state = state
        logger.info(f"MockDriver: State changed to {state}")
        return True

    def start_recording(self, out_dir: str, amount: Optional[int] = None) -> bool:
        if self._recording:
            logger.warning("MockDriver: Recording already in progress")
            return False
        self._recording = True
        logger.info(f"MockDriver: Recording started — dir={out_dir}, amount={amount}")
        return True

    def stop_recording(self) -> bool:
        self._recording = False
        logger.info("MockDriver: Recording stopped")
        return True

    def set_physical_location(self, location: str) -> bool:
        valid_locations = [
            "DEFAULT", "FRONT_CENTER_BOTTOM", "FRONT_RIGHT_BOTTOM",
            "FRONT_LEFT_BOTTOM", "REAR_RIGHT_BOTTOM", "REAR_LEFT_BOTTOM",
            "FRONT_RIGHT", "FRONT_LEFT",
        ]
        if location not in valid_locations:
            logger.error(f"MockDriver: Unknown location '{location}'")
            return False
        old_location = self._location
        self._location = location
        logger.info(f"MockDriver: Physical location changed {old_location} -> {location}")
        return True

    def get_physical_location(self) -> str:
        return self._location

    def enable_lldp(self) -> bool:
        self._lldp_enabled = True
        logger.info("MockDriver: LLDP enabled")
        return True

    def set_rloc_timeout(self, timeout_sec: int) -> bool:
        self._rloc_timeout = timeout_sec
        logger.info(f"MockDriver: RLOC timeout set to {timeout_sec}s")
        return True

    @property
    def state(self) -> str:
        return self._state

    @property
    def fw_version(self) -> str:
        return self._fw_version

    def set_statistics_window_size(self, fps: int = 10, latency: int = 1) -> None:
        logger.debug(f"MockDriver: Statistics window set — fps={fps}, latency={latency}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

