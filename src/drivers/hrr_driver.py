"""
HRR Radar Driver — wraps hrr_apis.Radar for HRR radars (MBAG project).

This driver uses the hrr_apis package (v0.2.0+) to communicate with
HRR radar hardware. HRR uses SODA frames instead of PC1.

Reference: hrr_apis_0.2.0_user_guide.html
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
    from hrr_apis import Radar as HRRRadar
    from external.response import ConnectResponseStatus
    HRR_APIS_AVAILABLE = True
except ImportError:
    HRR_APIS_AVAILABLE = False
    logger.warning("hrr_apis package not installed — HRR driver will not be functional")


class HRRDriver(RadarDriverBase):
    """
    Driver for HRR radars using hrr_apis package.

    HRR radars output SODA (Sensor Output Detection Array) frames
    instead of PC1 frames. The API is similar to BSR but with
    different data structures.

    Supports:
    - Context manager
    - SODA data acquisition
    - Heartbeat monitoring
    - Recording (HDF5)
    """

    def __init__(
        self,
        ip: str,
        radar_type: str = "HRR",
        password: Optional[str] = None,
    ) -> None:
        super().__init__(ip=ip, radar_type=radar_type, is_hrr=True, password=password)
        self._radar = None
        self._fw_version = ""
        self._state = "UNKNOWN"

        if HRR_APIS_AVAILABLE:
            self._radar = HRRRadar(ip=ip)
            logger.info(f"HRRDriver: hrr_apis.Radar instantiated at {ip}")
        else:
            logger.error("HRRDriver: hrr_apis not available")

    def connect(self, ping_timeout: int = 10) -> ConnectResponse:
        if not HRR_APIS_AVAILABLE or self._radar is None:
            return ConnectResponse(
                status=ConnectStatus.GENERAL_ERROR,
                message="hrr_apis not installed",
            )
        try:
            response = self._radar.connect(ping_timeout=ping_timeout)
            if response and response.status == ConnectResponseStatus.OK:
                self._connected = True
                logger.info(f"HRRDriver: Connected to HRR at {self.ip}")
                return ConnectResponse(
                    status=ConnectStatus.OK,
                    message="Connected successfully",
                )
            else:
                status_str = str(getattr(response, "status", "UNKNOWN"))
                return ConnectResponse(
                    status=ConnectStatus.GENERAL_ERROR,
                    message=f"Connect failed: {status_str}",
                )
        except Exception as e:
            logger.error(f"HRRDriver: Connect error: {e}")
            return ConnectResponse(status=ConnectStatus.GENERAL_ERROR, message=str(e))

    def disconnect(self) -> None:
        if self._radar and self._connected:
            try:
                self._radar.disconnect()
            except Exception as e:
                logger.warning(f"HRRDriver: Disconnect error (ignored): {e}")
            self._connected = False
            logger.info("HRRDriver: Disconnected")

    def ping(self, timeout: int = 5) -> bool:
        # HRR API doesn't have a dedicated ping; try heartbeat
        if not self._radar:
            return False
        try:
            hb = self._radar.get_heartbeat(timeout=timeout)
            return hb is not None
        except Exception:
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
            )
        except Exception as e:
            logger.error(f"HRRDriver: get_heartbeat error: {e}")
            return None

    def get_point_cloud(self, timeout: int = 5) -> Optional[PointCloudFrame]:
        """Get a SODA frame (HRR equivalent of point cloud)."""
        if not self._radar or not self._connected:
            return None
        try:
            soda = self._radar.get_soda(timeout=timeout)
            if soda is None:
                return None
            detections = []
            for i in range(len(soda.detections)):
                det = soda.detections[i]
                detections.append(DetectionData(
                    distance=float(det["HRR_F_Dtctn_Dist"]) * 0.005,
                    azimuth=float(det["HRR_F_Dtctn_Azi"]) * 5.0e-5 - 1.571,
                    elevation=float(det["HRR_F_Dtctn_Elev"]) * 5.0e-5 - 1.571,
                    velocity=float(det["HRR_F_Dtctn_RadVelo"]),
                    rcs=float(det["HRR_F_Dtctn_RCS"]),
                    x=float(det["x"]),
                    y=float(det["y"]),
                    z=float(det["z"]),
                ))
            return PointCloudFrame(
                cycle_count=soda.generic_header.get("HRR_F_Cycl_Count", 0),
                valid_detections=soda.radar_header.get("HRR_F_ValidDtctn", 0),
                detections=detections,
                latency_ms=getattr(soda, "latency", 0.0),
            )
        except Exception as e:
            logger.error(f"HRRDriver: get_point_cloud (SODA) error: {e}")
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
            logger.error(f"HRRDriver: get_statistics error: {e}")
            return StatisticsData()

    def update_fw(self, modality: Optional[str] = None, force: bool = False) -> bool:
        # HRR uses the bsr_apis update mechanism with is_hrr=True
        logger.warning("HRRDriver: FW update via hrr_apis not directly supported; use bsr_apis with is_hrr=True")
        return False

    def reset(self, reset_type: str = "COLD") -> bool:
        logger.warning("HRRDriver: Reset not directly supported via hrr_apis")
        return False

    def set_state(self, state: str) -> bool:
        logger.warning("HRRDriver: set_state not directly supported via hrr_apis")
        return False

    def start_recording(self, out_dir: str, amount: Optional[int] = None) -> bool:
        if not self._radar or not self._connected:
            return False
        try:
            return bool(self._radar.start_recording(out_dir, amount=amount))
        except Exception as e:
            logger.error(f"HRRDriver: start_recording error: {e}")
            return False

    def stop_recording(self) -> bool:
        if not self._radar or not self._connected:
            return False
        try:
            self._radar.stop_recording()
            return True
        except Exception as e:
            logger.error(f"HRRDriver: stop_recording error: {e}")
            return False

    def set_physical_location(self, location: str) -> bool:
        logger.warning("HRRDriver: LLDP not supported on HRR")
        return False

    def get_physical_location(self) -> str:
        return "UNKNOWN"

    def enable_lldp(self) -> bool:
        logger.warning("HRRDriver: LLDP not supported on HRR")
        return False

    def set_rloc_timeout(self, timeout_sec: int) -> bool:
        logger.warning("HRRDriver: RLOC timeout not supported on HRR")
        return False

    @property
    def state(self) -> str:
        return self._state

    @property
    def fw_version(self) -> str:
        return self._fw_version

    def _extract_temperatures(self, hb: Any) -> Dict[str, float]:
        temps = {}
        try:
            if hasattr(hb, "temperatures") and hb.temperatures:
                for attr in ["tsip_0", "tsip_1"]:
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

