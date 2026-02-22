"""
Abstract Base Class for Radar Drivers.

Defines the unified interface that all radar drivers (BSR, HRR, Mock) must implement.
This abstraction allows the test framework to work with any radar type transparently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class ConnectStatus(Enum):
    """Connection status codes aligned with bsr_apis/hrr_apis."""
    OK = "OK"
    NO_PING = "NO_PING"
    FW_VERSION_MISMATCH = "FW_VERSION_MISMATCH"
    NET_DB_UNAVAILABLE = "NET_DB_UNAVAILABLE"
    GENERAL_ERROR = "GENERAL_ERROR"
    CONNECTION_LOST = "CONNECTION_LOST"
    TIMEOUT = "TIMEOUT"


@dataclass
class ConnectResponse:
    """Response from a radar connection attempt."""
    status: ConnectStatus
    message: str = ""
    fw_version: str = ""
    sensor_id: str = ""
    physical_location: str = ""


@dataclass
class HeartbeatData:
    """Parsed heartbeat data from the radar."""
    beat_id: int = 0
    status: str = ""
    timestamp_sec: int = 0
    timestamp_nsec: int = 0
    sensor_id: str = ""
    sensor_type: str = ""
    fw_version: str = ""
    temperatures: Dict[str, float] = field(default_factory=dict)
    voltages: Dict[str, float] = field(default_factory=dict)
    error_counters: Dict[str, int] = field(default_factory=dict)
    uptime_sec: int = 0


@dataclass
class DetectionData:
    """Single radar detection."""
    distance: float = 0.0
    azimuth: float = 0.0
    elevation: float = 0.0
    velocity: float = 0.0
    rcs: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class PointCloudFrame:
    """A single frame of radar detections (PC1/SODA)."""
    cycle_count: int = 0
    timestamp_sec: int = 0
    timestamp_nsec: int = 0
    valid_detections: int = 0
    detections: List[DetectionData] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class StatisticsData:
    """Runtime statistics from the radar."""
    fps_current: float = 0.0
    fps_mean: float = 0.0
    fps_min: float = 0.0
    fps_max: float = 0.0
    latency_current_ms: float = 0.0
    latency_mean_ms: float = 0.0
    drops_counters: Dict[str, int] = field(default_factory=dict)
    sync_loss_counter: int = 0
    temperatures: Dict[str, float] = field(default_factory=dict)


class RadarDriverBase(ABC):
    """
    Abstract base class for all radar driver implementations.

    Wraps bsr_apis.Radar / hrr_apis.Radar with a unified interface
    so that tests can run against any radar type transparently.
    """

    def __init__(
        self,
        ip: str,
        radar_type: str,
        is_hrr: bool = False,
        password: Optional[str] = None,
    ) -> None:
        self.ip = ip
        self.radar_type = radar_type
        self.is_hrr = is_hrr
        self.password = password
        self._connected = False
        logger.info(f"RadarDriver [{radar_type}] initialized — IP={ip}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    def connect(self, ping_timeout: int = 10) -> ConnectResponse:
        """Establish connection to the radar."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the radar."""
        ...

    @abstractmethod
    def ping(self, timeout: int = 5) -> bool:
        """Ping the radar to verify connectivity."""
        ...

    @abstractmethod
    def get_heartbeat(self, timeout: int = 5) -> Optional[HeartbeatData]:
        """Get a heartbeat message from the radar."""
        ...

    @abstractmethod
    def get_point_cloud(self, timeout: int = 5) -> Optional[PointCloudFrame]:
        """Get a point cloud / SODA frame from the radar."""
        ...

    @abstractmethod
    def get_statistics(self) -> StatisticsData:
        """Get runtime statistics (FPS, latency, drops)."""
        ...

    @abstractmethod
    def update_fw(self, modality: Optional[str] = None, force: bool = False) -> bool:
        """Update radar firmware."""
        ...

    @abstractmethod
    def reset(self, reset_type: str = "COLD") -> bool:
        """Reset the radar."""
        ...

    @abstractmethod
    def set_state(self, state: str) -> bool:
        """Set radar state (STANDBY, SCANNING, FW_UPDATE)."""
        ...

    @abstractmethod
    def start_recording(self, out_dir: str, amount: Optional[int] = None) -> bool:
        """Start recording data."""
        ...

    @abstractmethod
    def stop_recording(self) -> bool:
        """Stop recording data."""
        ...

    # --- LLDP / Physical Awareness ---

    @abstractmethod
    def set_physical_location(self, location: str) -> bool:
        """Set the radar's physical location via LLDP."""
        ...

    @abstractmethod
    def get_physical_location(self) -> str:
        """Get the radar's current physical location."""
        ...

    @abstractmethod
    def enable_lldp(self) -> bool:
        """Enable LLDP in system DB."""
        ...

    @abstractmethod
    def set_rloc_timeout(self, timeout_sec: int) -> bool:
        """Set RLOC timeout in system DB."""
        ...

    # --- Properties ---

    @property
    @abstractmethod
    def state(self) -> str:
        """Current radar state."""
        ...

    @property
    @abstractmethod
    def fw_version(self) -> str:
        """Current firmware version."""
        ...

    def set_statistics_window_size(self, fps: int = 10, latency: int = 1) -> None:
        """Set statistics window size (optional override)."""
        pass

