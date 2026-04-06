"""Runtime models for the FC Lokal API service."""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field
from datetime import date, datetime


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
    grid_output_limit_watts: float | None = None
    battery_charge_limit_watts: float | None = None
    system_total_limit_watts: float | None = None

    def has_site_limits(self) -> bool:
        """Return whether site-level hardware limits are configured."""
        return any(
            value is not None
            for value in (
                self.grid_output_limit_watts,
                self.battery_charge_limit_watts,
                self.system_total_limit_watts,
            )
        )

    def effective_total_limit_watts(self) -> float | None:
        """Return the total PV production cap for the forecast."""
        if self.system_total_limit_watts is not None:
            return self.system_total_limit_watts
        return self.battery_charge_limit_watts


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
class PVGISPlaneBaseline:
    """Parsed PVGIS baseline data for one configured PV plane."""

    plane_name: str
    monthly_daily_energy_kwh: dict[int, float] = field(default_factory=dict)
    monthly_energy_kwh: dict[int, float] = field(default_factory=dict)
    annual_energy_kwh: float | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def expected_daily_energy_wh(self, *, day: date) -> float | None:
        """Return the expected average daily energy for the given date."""
        energy_kwh = self.monthly_daily_energy_kwh.get(day.month)
        if energy_kwh is None:
            return None
        return energy_kwh * 1000


@dataclass(slots=True)
class ForecastDebugInfo:
    """Intermediate values that help to understand the forecast."""

    pvgis_calibration_enabled: bool = False
    pvgis_calibration_active: bool = False
    pvgis_weight: float | None = None
    pvgis_expected_energy_today_wh: float | None = None
    pvgis_modeled_energy_today_wh: float | None = None
    pvgis_raw_scale: float | None = None
    pvgis_scale: float = 1.0
    modeled_power_now_watts: float | None = None
    modeled_energy_today_wh: float | None = None
    effective_live_pv_power_watts: float | None = None
    effective_live_pv_source: str | None = None
    battery_charge_watts: float | None = None
    grid_import_watts: float | None = None
    grid_export_watts: float | None = None
    live_power_scale: float | None = None
    live_energy_scale: float | None = None
    applied_total_limit_watts: float | None = None
    blended_scale: float = 1.0
