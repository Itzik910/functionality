"""
Radar Driver Abstraction Layer.

Provides a unified interface for communicating with different radar types:
- BSR32/BSRC via bsr_apis package
- HRR via hrr_apis package
- Mock driver for simulation/testing without hardware

The factory function `create_radar_driver()` returns the appropriate driver
based on the radar type and whether simulation mode is enabled.
"""

from src.drivers.radar_driver_base import RadarDriverBase, ConnectStatus
from src.drivers.driver_factory import create_radar_driver

__all__ = [
    "RadarDriverBase",
    "ConnectStatus",
    "create_radar_driver",
]

