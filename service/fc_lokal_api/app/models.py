"""Runtime models for the FC Lokal API service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class PlaneConfig:
    """Configuration for a single PV plane."""

    name: str
    declination: int
    azimuth: int
    kwp: float
    inverter_watts: float | None = None

    def open_meteo_azimuth(self) -> int:
        """Convert Home Assistant azimuth to Open-Meteo azimuth."""
        return int(self.azimuth - 180)

    def pvgis_aspect(self) -> int:
        """Convert Home Assistant azimuth to PVGIS aspect."""
        aspect = self.azimuth - 180
        if aspect > 180:
            return aspect - 360
        if aspect < -180:
            return aspect + 360
        return int(aspect)


@dataclass(slots=True)
class SiteConfig:
    """Site-wide configuration."""

    latitude: float
    longitude: float
    timezone: str
    planes: list[PlaneConfig]


@dataclass(slots=True)
class EstimateRequest:
    """Query override data received from FC Lokal."""

    actual: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    declination: int | None = None
    azimuth: int | None = None
    kwp: float | None = None
    inverter_kw: float | None = None
    extra_planes: list[PlaneConfig] = field(default_factory=list)


@dataclass(slots=True)
class WeatherPoint:
    """Single hourly weather point."""

    timestamp: datetime
    global_tilted_irradiance: float
    temperature_c: float | None = None
    cloud_cover: float | None = None


@dataclass(slots=True)
class LiveInputs:
    """Current live inputs gathered from Home Assistant."""

    pv_power_watts: float | None = None
    pv_energy_today_wh: float | None = None
    inverter_power_watts: float | None = None
    grid_power_watts: float | None = None
    battery_power_watts: float | None = None


@dataclass(slots=True)
class ForecastDebugInfo:
    """Intermediate values that help to understand the forecast."""

    modeled_power_now_watts: float | None = None
    modeled_energy_today_wh: float | None = None
    live_power_scale: float | None = None
    live_energy_scale: float | None = None
    blended_scale: float = 1.0
