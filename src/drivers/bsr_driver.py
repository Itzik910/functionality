"""
BSR Radar Driver — wraps bsr_apis.Radar for BSR32 and BSRC radars.

This driver uses the bsr_apis package (v5.4.1+) to communicate with
BSR32 and BSRC radar hardware. When bsr_apis is not installed, it
falls back to the mock driver.

Reference: bsr_apis_5.4.1_user_guide.html
"""

from __future__ import annotations

from typing import Any, Dict, Optional

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

try:
    from bsr_apis import (
        Radar as BSRRadar,
        ConnectResponseStatus,
        FWUpdateModality,
        PhysicalLocation,
        RadarState,
        ResetType,
        SetPhyLocResponseStatus,
    )
    BSR_APIS_AVAILABLE = True
except ImportError:
    BSR_APIS_AVAILABLE = False
    logger.warning("bsr_apis package not installed — BSR driver will not be functional")


class BSRDriver(RadarDriverBase):
    """
    Driver for BSR32 and BSRC radars using bsr_apis package.

    Supports:
    - Context manager (auto-disconnect)
    - FW update with DR64 modality
    - LLDP physical location control
    - PC1 point cloud data fetching
    - Heartbeat monitoring
    - Recording
    """

    def __init__(
        self,
        ip: str,
        radar_type: str = "BSR32",
        is_hrr: bool = False,
        password: Optional[str] = None,
        rtool_config: Any = None,
    ) -> None:
        super().__init__(ip=ip, radar_type=radar_type, is_hrr=is_hrr, password=password)
        self._radar = None
        self._rtool_config = rtool_config
        self._fw_version = ""
        self._state = "UNKNOWN"

        if BSR_APIS_AVAILABLE:
            kwargs: Dict[str, Any] = {"ip": ip}
            if is_hrr:
                kwargs["is_hrr"] = True
            if password:
                kwargs["password"] = password
            if rtool_config:
                kwargs["rtool_config"] = rtool_config
            self._radar = BSRRadar(**kwargs)
            logger.info(f"BSRDriver: bsr_apis.Radar instantiated for {radar_type} at {ip}")
        else:
            logger.error("BSRDriver: bsr_apis not available — cannot create real radar instance")

    def connect(self, ping_timeout: int = 10) -> ConnectResponse:
        if not BSR_APIS_AVAILABLE or self._radar is None:
            return ConnectResponse(
                status=ConnectStatus.GENERAL_ERROR,
                message="bsr_apis not installed",
            )
        try:
            response = self._radar.connect(ping_timeout=ping_timeout)
            if response:
                self._connected = True
                self._fw_version = getattr(self._radar, "supported_fw_version", "")
                location = getattr(self._radar, "physical_location", None)
                loc_name = location.name if location else "UNKNOWN"
                logger.info(f"BSRDriver: Connected to {self.radar_type} at {self.ip}")
                return ConnectResponse(
                    status=ConnectStatus.OK,
                    message="Connected successfully",
                    fw_version=self._fw_version,
                    physical_location=loc_name,
                )
            else:
                status_val = getattr(response, "status", None)
                status_name = status_val.name if status_val else "UNKNOWN"
                return ConnectResponse(
                    status=ConnectStatus(status_name) if status_name in ConnectStatus.__members__ else ConnectStatus.GENERAL_ERROR,
                    message=f"Connect failed: {status_name}",
                )
        except Exception as e:
            logger.error(f"BSRDriver: Connect error: {e}")
            return ConnectResponse(
                status=ConnectStatus.GENERAL_ERROR,
                message=str(e),
            )

    def disconnect(self) -> None:
        if self._radar and self._connected:
            try:
                self._radar.disconnect()
            except Exception as e:
                logger.warning(f"BSRDriver: Disconnect error (ignored): {e}")
            self._connected = False
            logger.info("BSRDriver: Disconnected")

    def ping(self, timeout: int = 5) -> bool:
        if not self._radar:
            return False
        try:
            response = self._radar.ping(timeout=timeout)
            return bool(response)
        except Exception as e:
            logger.debug(f"BSRDriver: Ping failed: {e}")
            return False

    def get_heartbeat(self, timeout: int = 5) -> Optional[HeartbeatData]:
        if not self._radar or not self._connected:
            return None
        try:
            hb = self._radar.get_heartbeat(timeout=timeout)
            if hb is None:
                return None
            return HeartbeatData(
                beat_id=getattr(hb, "beat_id", 0),
                status=str(getattr(hb, "status", "")),
                timestamp_sec=getattr(hb, "timestamp_sec", 0),
                timestamp_nsec=getattr(hb, "timestamp_nsec", 0),
                sensor_id=str(getattr(hb, "sensor_id", "")),
                sensor_type=str(getattr(hb, "sensor_type", "")),
                fw_version=str(getattr(getattr(hb, "versions", None), "fw_main_app_ver_high", "")),
                temperatures=self._extract_temperatures(hb),
                uptime_sec=getattr(hb, "up_time_sec", 0),
            )
        except Exception as e:
            logger.error(f"BSRDriver: get_heartbeat error: {e}")
            return None

    def get_point_cloud(self, timeout: int = 5) -> Optional[PointCloudFrame]:
        if not self._radar or not self._connected:
            return None
        try:
            pc1 = self._radar.get_pc1(timeout=timeout)
            if pc1 is None:
                return None
            detections = []
            for i in range(len(pc1.detections)):
                det = pc1.detections[i]
                detections.append(DetectionData(
                    distance=float(det.get("range", 0)) if hasattr(det, "get") else 0.0,
                    azimuth=float(det.get("azimuth", 0)) if hasattr(det, "get") else 0.0,
                    elevation=float(det.get("elevation", 0)) if hasattr(det, "get") else 0.0,
                    velocity=float(det.get("doppler", 0)) if hasattr(det, "get") else 0.0,
                    rcs=float(det.get("rcs", 0)) if hasattr(det, "get") else 0.0,
                    x=float(det.get("x", 0)) if hasattr(det, "get") else 0.0,
                    y=float(det.get("y", 0)) if hasattr(det, "get") else 0.0,
                    z=float(det.get("z", 0)) if hasattr(det, "get") else 0.0,
                ))
            return PointCloudFrame(
                cycle_count=pc1.generic_header.get("cycle_count", 0) if hasattr(pc1.generic_header, "get") else 0,
                valid_detections=len(detections),
                detections=detections,
                latency_ms=getattr(pc1, "latency", 0.0),
            )
        except Exception as e:
            logger.error(f"BSRDriver: get_point_cloud error: {e}")
            return None

    def get_statistics(self) -> StatisticsData:
        if not self._radar or not self._connected:
            return StatisticsData()
        try:
            stats = self._radar.get_statistics()
            return StatisticsData(
                fps_current=getattr(stats.fps, "current", 0.0),
                fps_mean=getattr(stats.fps, "mean", 0.0),
                fps_min=getattr(stats.fps, "minimum", 0.0),
                fps_max=getattr(stats.fps, "maximum", 0.0),
                latency_current_ms=getattr(stats.latency, "current", 0.0),
                latency_mean_ms=getattr(stats.latency, "mean", 0.0),
                sync_loss_counter=getattr(stats, "sync_loss_counter", 0),
            )
        except Exception as e:
            logger.error(f"BSRDriver: get_statistics error: {e}")
            return StatisticsData()

    def update_fw(self, modality: Optional[str] = None, force: bool = False) -> bool:
        if not self._radar:
            return False
        try:
            if modality and BSR_APIS_AVAILABLE:
                mod = getattr(FWUpdateModality, modality, FWUpdateModality.DR64)
                return bool(self._radar.update_fw(mod, force=force))
            return bool(self._radar.update_fw(force=force))
        except Exception as e:
            logger.error(f"BSRDriver: FW update error: {e}")
            return False

    def reset(self, reset_type: str = "COLD") -> bool:
        if not self._radar:
            return False
        try:
            rt = getattr(ResetType, reset_type, ResetType.COLD) if BSR_APIS_AVAILABLE else None
            return bool(self._radar.reset(rt))
        except Exception as e:
            logger.error(f"BSRDriver: Reset error: {e}")
            return False

    def set_state(self, state: str) -> bool:
        if not self._radar:
            return False
        try:
            rs = getattr(RadarState, state, None) if BSR_APIS_AVAILABLE else None
            if rs is None:
                return False
            return bool(self._radar.set_state(rs))
        except Exception as e:
            logger.error(f"BSRDriver: set_state error: {e}")
            return False

    def start_recording(self, out_dir: str, amount: Optional[int] = None) -> bool:
        if not self._radar or not self._connected:
            return False
        try:
            return bool(self._radar.start_recording(out_dir, amount=amount))
        except Exception as e:
            logger.error(f"BSRDriver: start_recording error: {e}")
            return False

    def stop_recording(self) -> bool:
        if not self._radar or not self._connected:
            return False
        try:
            self._radar.stop_recording()
            return True
        except Exception as e:
            logger.error(f"BSRDriver: stop_recording error: {e}")
            return False

    def set_physical_location(self, location: str) -> bool:
        if not self._radar or not BSR_APIS_AVAILABLE:
            return False
        try:
            loc = getattr(PhysicalLocation, location, None)
            if loc is None:
                logger.error(f"BSRDriver: Unknown location: {location}")
                return False
            kwargs = {}
            if self.password:
                kwargs["password"] = self.password
            response = self._radar.set_physical_location(physical_location=loc, **kwargs)
            if response.status == SetPhyLocResponseStatus.OK:
                logger.info(f"BSRDriver: Physical location set to {location}")
                return True
            elif response.status == SetPhyLocResponseStatus.CONNECTION_LOST:
                logger.error("BSRDriver: Connection lost during LLDP location change!")
                self._connected = False
                return False
            else:
                logger.error(f"BSRDriver: set_physical_location failed: {response.status}")
                return False
        except Exception as e:
            logger.error(f"BSRDriver: set_physical_location error: {e}")
            return False

    def get_physical_location(self) -> str:
        if not self._radar:
            return "UNKNOWN"
        try:
            loc = self._radar.physical_location
            return loc.name if loc else "UNKNOWN"
        except Exception as e:
            logger.debug(f"BSRDriver: get_physical_location error: {e}")
            return "UNKNOWN"

    def enable_lldp(self) -> bool:
        if not self._radar:
            return False
        try:
            status = self._radar.system_db.set_lldp_state(lldp_enable=True)
            return bool(status)
        except Exception as e:
            logger.error(f"BSRDriver: enable_lldp error: {e}")
            return False

    def set_rloc_timeout(self, timeout_sec: int) -> bool:
        if not self._radar:
            return False
        try:
            status = self._radar.system_db.set_rloc_timeout(timeout=timeout_sec)
            return bool(status)
        except Exception as e:
            logger.error(f"BSRDriver: set_rloc_timeout error: {e}")
            return False

    @property
    def state(self) -> str:
        if not self._radar:
            return "UNKNOWN"
        try:
            return self._radar.state.name
        except Exception:
            return "UNKNOWN"

    @property
    def fw_version(self) -> str:
        return self._fw_version

    def set_statistics_window_size(self, fps: int = 10, latency: int = 1) -> None:
        if self._radar and self._connected:
            try:
                self._radar.set_statistics_window_size(fps=fps, latency=latency)
            except Exception as e:
                logger.debug(f"BSRDriver: set_statistics_window_size error: {e}")

    def _extract_temperatures(self, hb: Any) -> Dict[str, float]:
        """Extract temperature readings from a heartbeat object."""
        temps = {}
        try:
            if hasattr(hb, "temperatures") and hb.temperatures:
                for attr in ["tsip_0", "tsip_1", "tsip_2", "tsip_3"]:
                    val = getattr(hb.temperatures, attr, None)
                    if val is not None:
                        temps[attr] = float(val)
        except Exception:
            pass
        return temps

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

