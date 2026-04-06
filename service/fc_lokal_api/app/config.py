"""Configuration loader for the FC Lokal API service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import PlaneConfig, SiteConfig


@dataclass(slots=True)
class HomeAssistantSensors:
    """Configured Home Assistant sensor entity IDs."""

    pv_power_entity_id: str | None = None
    pv_energy_today_entity_id: str | None = None
    inverter_power_entity_id: str | None = None
    grid_power_entity_id: str | None = None
    battery_power_entity_id: str | None = None


@dataclass(slots=True)
class HomeAssistantConfig:
    """Home Assistant connectivity configuration."""

    base_url: str | None = None
    token: str | None = None
    verify_ssl: bool = True
    timeout_seconds: int = 10
    sensors: HomeAssistantSensors = field(default_factory=HomeAssistantSensors)

    @property
    def enabled(self) -> bool:
        """Return whether HA integration is configured."""
        return bool(self.base_url and self.token)


@dataclass(slots=True)
class OpenMeteoConfig:
    """Open-Meteo configuration."""

    base_url: str = "https://api.open-meteo.com/v1/forecast"
    forecast_days: int = 3
    model: str = "best_match"
    timeout_seconds: int = 15


@dataclass(slots=True)
class PVGISConfig:
    """PVGIS configuration."""

    base_url: str = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
    enabled: bool = True
    loss_percent: float = 14.0
    pvtechchoice: str = "crystSi"
    mountingplace: str = "free"
    usehorizon: bool = True
    timeout_seconds: int = 30


@dataclass(slots=True)
class EngineConfig:
    """Forecast tuning parameters."""

    min_scale: float = 0.25
    max_scale: float = 1.6
    live_power_weight: float = 0.55
    daily_energy_weight: float = 0.45
    low_light_threshold_wm2: float = 10.0
    temperature_coefficient_per_c: float = 0.004


@dataclass(slots=True)
class AppConfig:
    """Application configuration."""

    site: SiteConfig
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    open_meteo: OpenMeteoConfig = field(default_factory=OpenMeteoConfig)
    pvgis: PVGISConfig = field(default_factory=PVGISConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)


def load_config(path: str | Path) -> AppConfig:
    """Load the application config from YAML."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    weather_defaults = OpenMeteoConfig()
    pvgis_defaults = PVGISConfig()

    site_raw = raw.get("site", {})
    planes_raw = site_raw.get("planes") or [site_raw.get("plane", {})]
    planes = [_load_plane(index, plane_raw) for index, plane_raw in enumerate(planes_raw, 1)]

    site = SiteConfig(
        latitude=float(site_raw["latitude"]),
        longitude=float(site_raw["longitude"]),
        timezone=str(site_raw.get("timezone", "Europe/Berlin")),
        planes=planes,
    )

    ha_raw = raw.get("home_assistant", {})
    sensors_raw = ha_raw.get("sensors", {})
    home_assistant = HomeAssistantConfig(
        base_url=_strip_or_none(ha_raw.get("base_url")),
        token=_strip_or_none(ha_raw.get("token")),
        verify_ssl=bool(ha_raw.get("verify_ssl", True)),
        timeout_seconds=int(ha_raw.get("timeout_seconds", 10)),
        sensors=HomeAssistantSensors(
            pv_power_entity_id=_strip_or_none(sensors_raw.get("pv_power_entity_id")),
            pv_energy_today_entity_id=_strip_or_none(
                sensors_raw.get("pv_energy_today_entity_id")
            ),
            inverter_power_entity_id=_strip_or_none(
                sensors_raw.get("inverter_power_entity_id")
            ),
            grid_power_entity_id=_strip_or_none(sensors_raw.get("grid_power_entity_id")),
            battery_power_entity_id=_strip_or_none(
                sensors_raw.get("battery_power_entity_id")
            ),
        ),
    )

    weather_raw = raw.get("open_meteo", {})
    pvgis_raw = raw.get("pvgis", {})
    engine_raw = raw.get("engine", {})

    return AppConfig(
        site=site,
        home_assistant=home_assistant,
        open_meteo=OpenMeteoConfig(
            base_url=str(weather_raw.get("base_url", weather_defaults.base_url)),
            forecast_days=int(weather_raw.get("forecast_days", 3)),
            model=str(weather_raw.get("model", "best_match")),
            timeout_seconds=int(weather_raw.get("timeout_seconds", 15)),
        ),
        pvgis=PVGISConfig(
            base_url=str(pvgis_raw.get("base_url", pvgis_defaults.base_url)),
            enabled=bool(pvgis_raw.get("enabled", True)),
            loss_percent=float(pvgis_raw.get("loss_percent", 14.0)),
            pvtechchoice=str(pvgis_raw.get("pvtechchoice", "crystSi")),
            mountingplace=str(pvgis_raw.get("mountingplace", "free")),
            usehorizon=bool(pvgis_raw.get("usehorizon", True)),
            timeout_seconds=int(pvgis_raw.get("timeout_seconds", 30)),
        ),
        engine=EngineConfig(
            min_scale=float(engine_raw.get("min_scale", 0.25)),
            max_scale=float(engine_raw.get("max_scale", 1.6)),
            live_power_weight=float(engine_raw.get("live_power_weight", 0.55)),
            daily_energy_weight=float(engine_raw.get("daily_energy_weight", 0.45)),
            low_light_threshold_wm2=float(
                engine_raw.get("low_light_threshold_wm2", 10.0)
            ),
            temperature_coefficient_per_c=float(
                engine_raw.get("temperature_coefficient_per_c", 0.004)
            ),
        ),
    )


def _load_plane(index: int, raw: dict[str, Any]) -> PlaneConfig:
    """Load a single plane config."""
    return PlaneConfig(
        name=str(raw.get("name", f"plane_{index}")),
        declination=int(raw["declination"]),
        azimuth=int(raw["azimuth"]),
        kwp=float(raw["kwp"]),
        inverter_watts=(
            float(raw["inverter_watts"]) if raw.get("inverter_watts") is not None else None
        ),
    )


def _strip_or_none(value: Any) -> str | None:
    """Normalize optional strings."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
