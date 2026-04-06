"""Forecast engine for the FC Lokal API service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .clients.ha import HomeAssistantClient
from .clients.open_meteo import OpenMeteoClient
from .clients.pvgis import PVGISClient
from .config import AppConfig
from .models import EstimateRequest, ForecastDebugInfo, LiveInputs, PlaneConfig, SiteConfig

LOGGER = logging.getLogger(__name__)


class ForecastEngine:
    """Combine weather, PVGIS, and Home Assistant live data."""

    def __init__(
        self,
        *,
        config: AppConfig,
        weather_client: OpenMeteoClient,
        ha_client: HomeAssistantClient | None = None,
        pvgis_client: PVGISClient | None = None,
    ) -> None:
        """Initialize the engine."""
        self._config = config
        self._weather_client = weather_client
        self._ha_client = ha_client
        self._pvgis_client = pvgis_client

    async def build_estimate(self, request: EstimateRequest) -> dict[str, Any]:
        """Build a Forecast.Solar-compatible estimate payload."""
        site = self._resolve_site(request)
        live_inputs = await self._fetch_live_inputs(request)

        plane_forecasts = await asyncio.gather(
            *[
                self._weather_client.fetch_plane_forecast(site=site, plane=plane)
                for plane in site.planes
            ]
        )

        modeled = self._combine_plane_forecasts(site=site, plane_forecasts=plane_forecasts)
        adjusted, _debug = self._apply_live_correction(
            timestamps_to_power=modeled,
            live_inputs=live_inputs,
            timezone=site.timezone,
        )
        return self._to_forecast_solar_payload(
            timestamps_to_power=adjusted,
            timezone=site.timezone,
        )

    async def build_health(self) -> dict[str, Any]:
        """Return a simple health snapshot."""
        baseline = None
        if self._pvgis_client and self._config.pvgis.enabled:
            try:
                baseline = await self._pvgis_client.fetch_baseline(
                    site=self._config.site,
                    plane=self._config.site.planes[0],
                )
            except Exception as err:  # noqa: BLE001
                baseline = {"error": str(err)}

        return {
            "status": "ok",
            "ha_enabled": self._config.home_assistant.enabled,
            "plane_count": len(self._config.site.planes),
            "open_meteo_model": self._config.open_meteo.model,
            "pvgis_enabled": self._config.pvgis.enabled,
            "pvgis_sample": baseline,
        }

    async def _fetch_live_inputs(self, request: EstimateRequest) -> LiveInputs:
        """Fetch live inputs from Home Assistant and query overrides."""
        live_inputs = LiveInputs()
        if self._ha_client and self._config.home_assistant.enabled:
            try:
                live_inputs = await self._ha_client.fetch_live_inputs()
            except Exception as err:  # noqa: BLE001
                LOGGER.warning("Failed to fetch live inputs from Home Assistant: %s", err)

        if request.actual is not None:
            live_inputs.pv_energy_today_wh = self._normalize_unknown_energy(request.actual)

        return live_inputs

    def _resolve_site(self, request: EstimateRequest) -> SiteConfig:
        """Apply request-level overrides on top of the configured site."""
        latitude = request.latitude or self._config.site.latitude
        longitude = request.longitude or self._config.site.longitude

        has_plane_override = any(
            value is not None
            for value in (
                request.declination,
                request.azimuth,
                request.kwp,
                request.inverter_kw,
            )
        ) or bool(request.extra_planes)

        base_plane = self._config.site.planes[0]
        first_plane = replace(
            base_plane,
            declination=request.declination or base_plane.declination,
            azimuth=request.azimuth or base_plane.azimuth,
            kwp=request.kwp or base_plane.kwp,
            inverter_watts=(
                request.inverter_kw * 1000
                if request.inverter_kw is not None
                else base_plane.inverter_watts
            ),
        )

        planes = (
            [first_plane, *request.extra_planes]
            if has_plane_override
            else list(self._config.site.planes)
        )

        return SiteConfig(
            latitude=latitude,
            longitude=longitude,
            timezone=self._config.site.timezone,
            planes=planes,
        )

    def _combine_plane_forecasts(
        self,
        *,
        site: SiteConfig,
        plane_forecasts: list[list[Any]],
    ) -> dict[datetime, float]:
        """Convert weather forecasts into combined AC power per timestamp."""
        combined: dict[datetime, float] = {}
        now = datetime.now(ZoneInfo(site.timezone))

        for plane, forecast_points in zip(site.planes, plane_forecasts, strict=True):
            for point in forecast_points:
                if point.timestamp < now.replace(minute=0, second=0, microsecond=0):
                    continue

                gti = max(point.global_tilted_irradiance, 0.0)
                if gti < self._config.engine.low_light_threshold_wm2:
                    plane_power = 0.0
                else:
                    plane_power = plane.kwp * 1000 * (gti / 1000)
                    if point.temperature_c is not None and point.temperature_c > 25:
                        plane_power *= 1 - (
                            (point.temperature_c - 25)
                            * self._config.engine.temperature_coefficient_per_c
                        )
                    plane_power = max(plane_power, 0.0)

                if plane.inverter_watts is not None:
                    plane_power = min(plane_power, plane.inverter_watts)

                combined[point.timestamp] = combined.get(point.timestamp, 0.0) + plane_power

        return dict(sorted(combined.items()))

    def _apply_live_correction(
        self,
        *,
        timestamps_to_power: dict[datetime, float],
        live_inputs: LiveInputs,
        timezone: str,
    ) -> tuple[dict[datetime, float], ForecastDebugInfo]:
        """Blend live Home Assistant values into the weather model."""
        debug = ForecastDebugInfo()
        if not timestamps_to_power:
            return timestamps_to_power, debug

        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        modeled_power_now = timestamps_to_power.get(current_hour)
        debug.modeled_power_now_watts = modeled_power_now

        modeled_energy_today = sum(
            power
            for timestamp, power in timestamps_to_power.items()
            if timestamp.astimezone(tz).date() == now.date() and timestamp <= current_hour
        )
        debug.modeled_energy_today_wh = modeled_energy_today

        power_scale = self._scale_from_live_value(
            live_value=live_inputs.pv_power_watts or live_inputs.inverter_power_watts,
            modeled_value=modeled_power_now,
        )
        energy_scale = self._scale_from_live_value(
            live_value=live_inputs.pv_energy_today_wh,
            modeled_value=modeled_energy_today,
        )

        debug.live_power_scale = power_scale
        debug.live_energy_scale = energy_scale

        weighted_scales: list[tuple[float, float]] = []
        if power_scale is not None:
            weighted_scales.append((power_scale, self._config.engine.live_power_weight))
        if energy_scale is not None:
            weighted_scales.append((energy_scale, self._config.engine.daily_energy_weight))

        if not weighted_scales:
            return timestamps_to_power, debug

        total_weight = sum(weight for _, weight in weighted_scales)
        debug.blended_scale = sum(scale * weight for scale, weight in weighted_scales) / total_weight

        return (
            {
                timestamp: max(power * debug.blended_scale, 0.0)
                for timestamp, power in timestamps_to_power.items()
            },
            debug,
        )

    def _scale_from_live_value(
        self, *, live_value: float | None, modeled_value: float | None
    ) -> float | None:
        """Turn a live value into a clipped scale factor."""
        if live_value is None or modeled_value in {None, 0}:
            return None
        scale = live_value / modeled_value
        return max(self._config.engine.min_scale, min(self._config.engine.max_scale, scale))

    @staticmethod
    def _normalize_unknown_energy(value: float) -> float:
        """Normalize an unknown daily energy input to watt-hours."""
        return value * 1000 if abs(value) <= 100 else value

    @staticmethod
    def _to_forecast_solar_payload(
        *, timestamps_to_power: dict[datetime, float], timezone: str
    ) -> dict[str, Any]:
        """Convert the internal power map to the expected response format."""
        tz = ZoneInfo(timezone)
        watts = {timestamp.isoformat(): round(power, 3) for timestamp, power in timestamps_to_power.items()}
        watt_hours_period = {
            timestamp.isoformat(): round(power, 3)
            for timestamp, power in timestamps_to_power.items()
        }

        day_totals: dict[datetime, float] = {}
        for timestamp, power in timestamps_to_power.items():
            local_day = timestamp.astimezone(tz).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            day_totals[local_day] = day_totals.get(local_day, 0.0) + power

        watt_hours_day = {
            day.isoformat(): round(total, 3) for day, total in sorted(day_totals.items())
        }

        return {
            "result": {
                "watts": watts,
                "watt_hours_period": watt_hours_period,
                "watt_hours_day": watt_hours_day,
            },
            "message": {
                "ratelimit": {"limit": 9999},
                "info": {"timezone": timezone},
            },
        }
