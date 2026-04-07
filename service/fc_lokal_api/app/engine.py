"""Forecast engine for the FC Lokal API service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .clients.ha import HomeAssistantClient
from .clients.open_meteo import OpenMeteoClient
from .clients.pvgis import PVGISClient
from .config import AppConfig
from .models import (
    EstimateRequest,
    ForecastDebugInfo,
    LiveInputs,
    PVGISPlaneBaseline,
    PlaneConfig,
    SiteConfig,
)

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
        pvgis_adjusted, _pvgis_debug = await self._apply_pvgis_calibration(
            timestamps_to_power=modeled,
            site=site,
            timezone=site.timezone,
        )
        adjusted, _debug = self._apply_live_correction(
            timestamps_to_power=pvgis_adjusted,
            live_inputs=live_inputs,
            site=site,
            timezone=site.timezone,
        )
        effective_total_limit_watts = self._effective_total_limit_watts(
            site=site,
            live_inputs=live_inputs,
        )
        limited = self._apply_total_limit(
            timestamps_to_power=adjusted,
            total_limit_watts=effective_total_limit_watts,
        )
        return self._to_forecast_solar_payload(
            timestamps_to_power=limited,
            timezone=site.timezone,
        )

    async def build_health(self) -> dict[str, Any]:
        """Return a simple health snapshot."""
        baseline = None
        live_inputs = None
        pvgis_calibration = await self._build_health_pvgis_calibration()
        if self._pvgis_client and self._config.pvgis.enabled:
            try:
                baseline = await self._pvgis_client.fetch_baseline(
                    site=self._config.site,
                    plane=self._config.site.planes[0],
                )
            except Exception as err:  # noqa: BLE001
                baseline = {"error": str(err)}

        if self._ha_client and self._config.home_assistant.enabled:
            try:
                raw_live_inputs = await self._ha_client.fetch_live_inputs()
                live_power, power_source, battery_charge, grid_import, grid_export = (
                    self._resolve_live_pv_power(
                        live_inputs=raw_live_inputs,
                        site=self._config.site,
                        total_limit_watts=self._effective_total_limit_watts(
                            site=self._config.site,
                            live_inputs=raw_live_inputs,
                        ),
                    )
                )
                live_inputs = {
                    "pv_power_watts": raw_live_inputs.pv_power_watts,
                    "pv_energy_today_wh": raw_live_inputs.pv_energy_today_wh,
                    "inverter_power_watts": raw_live_inputs.inverter_power_watts,
                    "grid_power_watts": raw_live_inputs.grid_power_watts,
                    "battery_power_watts": raw_live_inputs.battery_power_watts,
                    "battery_soc_percent": raw_live_inputs.battery_soc_percent,
                    "effective_live_pv_power_watts": live_power,
                    "effective_live_pv_source": power_source,
                    "battery_charge_watts": battery_charge,
                    "grid_import_watts": grid_import,
                    "grid_export_watts": grid_export,
                    "effective_total_limit_watts": self._effective_total_limit_watts(
                        site=self._config.site,
                        live_inputs=raw_live_inputs,
                    ),
                }
            except Exception as err:  # noqa: BLE001
                live_inputs = {"error": str(err)}

        return {
            "status": "ok",
            "ha_enabled": self._config.home_assistant.enabled,
            "plane_count": len(self._config.site.planes),
            "open_meteo_model": self._config.open_meteo.model,
            "pvgis_enabled": self._config.pvgis.enabled,
            "limits": {
                "grid_output_limit_watts": self._config.site.grid_output_limit_watts,
                "battery_charge_limit_watts": self._config.site.battery_charge_limit_watts,
                "system_total_limit_watts": self._config.site.system_total_limit_watts,
            },
            "live_inputs": live_inputs,
            "pvgis_sample": baseline,
            "pvgis_calibration": pvgis_calibration,
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
            grid_output_limit_watts=(
                request.inverter_kw * 1000
                if request.inverter_kw is not None
                else self._config.site.grid_output_limit_watts
            ),
            battery_charge_limit_watts=self._config.site.battery_charge_limit_watts,
            system_total_limit_watts=self._config.site.system_total_limit_watts,
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
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for plane, forecast_points in zip(site.planes, plane_forecasts, strict=True):
            for point in forecast_points:
                # Keep the current day's earlier slots so HA charts do not drop the
                # already reached forecast line/bar as the day progresses.
                if point.timestamp < start_of_today:
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

                if not site.has_site_limits() and plane.inverter_watts is not None:
                    plane_power = min(plane_power, plane.inverter_watts)

                combined[point.timestamp] = combined.get(point.timestamp, 0.0) + plane_power

        return dict(sorted(combined.items()))

    async def _apply_pvgis_calibration(
        self,
        *,
        timestamps_to_power: dict[datetime, float],
        site: SiteConfig,
        timezone: str,
    ) -> tuple[dict[datetime, float], ForecastDebugInfo]:
        """Scale the weather curve toward a PVGIS seasonal baseline."""
        weight = self._normalized_pvgis_weight()
        debug = ForecastDebugInfo(
            pvgis_calibration_enabled=self._pvgis_calibration_enabled(),
            pvgis_weight=weight,
        )
        if not timestamps_to_power or not debug.pvgis_calibration_enabled:
            return timestamps_to_power, debug
        if self._pvgis_client is None:
            return timestamps_to_power, debug

        try:
            baselines = await asyncio.gather(
                *[
                    self._pvgis_client.fetch_plane_baseline(site=site, plane=plane)
                    for plane in site.planes
                ]
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Failed to fetch PVGIS baselines for calibration: %s", err)
            return timestamps_to_power, debug

        tz = ZoneInfo(timezone)
        modeled_daily_energy_wh = self._daily_energy_by_local_day(
            timestamps_to_power=timestamps_to_power,
            timezone=tz,
        )
        expected_daily_energy_wh = self._expected_pvgis_energy_by_local_day(
            baselines=baselines,
            days=list(modeled_daily_energy_wh),
        )

        if not expected_daily_energy_wh:
            LOGGER.debug("Skipping PVGIS calibration because no daily baseline could be derived")
            return timestamps_to_power, debug

        today = datetime.now(tz).date()
        debug.pvgis_modeled_energy_today_wh = modeled_daily_energy_wh.get(today)
        debug.pvgis_expected_energy_today_wh = expected_daily_energy_wh.get(today)

        day_scales: dict[date, float] = {}
        for day, modeled_energy_wh in modeled_daily_energy_wh.items():
            expected_energy_wh = expected_daily_energy_wh.get(day)
            raw_scale = self._raw_scale(
                live_value=expected_energy_wh,
                modeled_value=modeled_energy_wh,
            )
            if raw_scale is None:
                continue

            blended_scale = self._clip_scale(1.0 + (raw_scale - 1.0) * weight)
            day_scales[day] = blended_scale
            if day == today:
                debug.pvgis_raw_scale = raw_scale
                debug.pvgis_scale = blended_scale

        if not day_scales:
            LOGGER.debug("Skipping PVGIS calibration because no valid daily factors were available")
            return timestamps_to_power, debug

        adjusted = {
            timestamp: max(
                power * day_scales.get(timestamp.astimezone(tz).date(), 1.0),
                0.0,
            )
            for timestamp, power in timestamps_to_power.items()
        }
        today_scale = day_scales.get(today)
        if today_scale is not None:
            debug.pvgis_calibration_active = abs(today_scale - 1.0) > 1e-6
        else:
            debug.pvgis_calibration_active = any(
                abs(scale - 1.0) > 1e-6 for scale in day_scales.values()
            )
        LOGGER.debug(
            "Applied PVGIS calibration: weight=%.3f today_expected_wh=%s "
            "today_modeled_wh=%s today_raw_scale=%s today_factor=%s",
            debug.pvgis_weight,
            debug.pvgis_expected_energy_today_wh,
            debug.pvgis_modeled_energy_today_wh,
            debug.pvgis_raw_scale,
            debug.pvgis_scale,
        )
        return dict(sorted(adjusted.items())), debug

    def _apply_live_correction(
        self,
        *,
        timestamps_to_power: dict[datetime, float],
        live_inputs: LiveInputs,
        site: SiteConfig,
        timezone: str,
    ) -> tuple[dict[datetime, float], ForecastDebugInfo]:
        """Blend live Home Assistant values into the weather model."""
        debug = ForecastDebugInfo()
        if not timestamps_to_power:
            return timestamps_to_power, debug

        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        effective_total_limit_watts = self._effective_total_limit_watts(
            site=site,
            live_inputs=live_inputs,
        )
        debug.applied_total_limit_watts = effective_total_limit_watts
        debug.battery_soc_percent = live_inputs.battery_soc_percent

        modeled_power_now = timestamps_to_power.get(current_hour)
        debug.modeled_power_now_watts = modeled_power_now

        modeled_energy_today = sum(
            power
            for timestamp, power in timestamps_to_power.items()
            if timestamp.astimezone(tz).date() == now.date() and timestamp <= current_hour
        )
        debug.modeled_energy_today_wh = modeled_energy_today

        (
            effective_live_pv_power,
            effective_live_pv_source,
            battery_charge_watts,
            grid_import_watts,
            grid_export_watts,
        ) = self._resolve_live_pv_power(
            live_inputs=live_inputs,
            site=site,
            total_limit_watts=effective_total_limit_watts,
        )
        debug.effective_live_pv_power_watts = effective_live_pv_power
        debug.effective_live_pv_source = effective_live_pv_source
        debug.battery_charge_watts = battery_charge_watts
        debug.grid_import_watts = grid_import_watts
        debug.grid_export_watts = grid_export_watts

        power_scale = self._scale_from_live_value(
            live_value=effective_live_pv_power,
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

        adjusted = {
            # Keep historical slots untouched; only adapt the newest forecast horizon.
            timestamp: (
                max(power * debug.blended_scale, 0.0)
                if timestamp >= current_hour
                else power
            )
            for timestamp, power in timestamps_to_power.items()
        }
        return (adjusted, debug)

    def _scale_from_live_value(
        self, *, live_value: float | None, modeled_value: float | None
    ) -> float | None:
        """Turn a live value into a clipped scale factor."""
        scale = self._raw_scale(live_value=live_value, modeled_value=modeled_value)
        if scale is None:
            return None
        return self._clip_scale(scale)

    def _apply_total_limit(
        self,
        *,
        timestamps_to_power: dict[datetime, float],
        total_limit_watts: float | None,
    ) -> dict[datetime, float]:
        """Apply the configured total system cap as the final forecast step."""
        if total_limit_watts is None:
            return timestamps_to_power
        return {
            timestamp: min(power, total_limit_watts)
            for timestamp, power in timestamps_to_power.items()
        }

    async def _build_health_pvgis_calibration(self) -> dict[str, Any]:
        """Build calibration debug data for the health endpoint."""
        calibration = {
            "enabled": self._pvgis_calibration_enabled(),
            "active": False,
            "factor": None,
            "expected_energy_today_wh": None,
            "modeled_energy_today_wh": None,
            "weight": self._normalized_pvgis_weight(),
        }
        if not calibration["enabled"]:
            return calibration

        try:
            plane_forecasts = await asyncio.gather(
                *[
                    self._weather_client.fetch_plane_forecast(
                        site=self._config.site,
                        plane=plane,
                    )
                    for plane in self._config.site.planes
                ]
            )
            modeled = self._combine_plane_forecasts(
                site=self._config.site,
                plane_forecasts=plane_forecasts,
            )
            _, debug = await self._apply_pvgis_calibration(
                timestamps_to_power=modeled,
                site=self._config.site,
                timezone=self._config.site.timezone,
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Failed to build PVGIS calibration health data: %s", err)
            calibration["error"] = str(err)
            return calibration

        calibration["active"] = debug.pvgis_calibration_active
        calibration["factor"] = debug.pvgis_scale if debug.pvgis_calibration_active else 1.0
        calibration["expected_energy_today_wh"] = debug.pvgis_expected_energy_today_wh
        calibration["modeled_energy_today_wh"] = debug.pvgis_modeled_energy_today_wh
        calibration["raw_scale"] = debug.pvgis_raw_scale
        return calibration

    def _daily_energy_by_local_day(
        self,
        *,
        timestamps_to_power: dict[datetime, float],
        timezone: ZoneInfo,
    ) -> dict[date, float]:
        """Sum hourly forecast values into per-day energy buckets."""
        daily_energy_wh: dict[date, float] = {}
        for timestamp, power in timestamps_to_power.items():
            local_day = timestamp.astimezone(timezone).date()
            daily_energy_wh[local_day] = daily_energy_wh.get(local_day, 0.0) + power
        return dict(sorted(daily_energy_wh.items()))

    def _expected_pvgis_energy_by_local_day(
        self,
        *,
        baselines: list[PVGISPlaneBaseline],
        days: list[date],
    ) -> dict[date, float]:
        """Resolve summed PVGIS expected daily energy for each forecast day."""
        expected_daily_energy_wh: dict[date, float] = {}
        for day in days:
            total_energy_wh = 0.0
            found_any = False
            for baseline in baselines:
                plane_energy_wh = baseline.expected_daily_energy_wh(day=day)
                if plane_energy_wh is None:
                    continue
                total_energy_wh += plane_energy_wh
                found_any = True
            if found_any:
                expected_daily_energy_wh[day] = total_energy_wh
        return expected_daily_energy_wh

    def _pvgis_calibration_enabled(self) -> bool:
        """Return whether PVGIS-based pre-calibration is active."""
        return (
            self._config.engine.use_pvgis_calibration
            and self._config.pvgis.enabled
            and self._pvgis_client is not None
        )

    def _normalized_pvgis_weight(self) -> float:
        """Clamp the configurable PVGIS blending weight to a safe range."""
        return max(0.0, min(1.0, self._config.engine.pvgis_weight))

    def _clip_scale(self, scale: float) -> float:
        """Clamp any scale factor to the configured safety range."""
        return max(self._config.engine.min_scale, min(self._config.engine.max_scale, scale))

    @staticmethod
    def _raw_scale(
        *, live_value: float | None, modeled_value: float | None
    ) -> float | None:
        """Calculate an unclipped raw ratio between two values."""
        if live_value is None or modeled_value in {None, 0}:
            return None
        return live_value / modeled_value

    def _resolve_live_pv_power(
        self,
        *,
        live_inputs: LiveInputs,
        site: SiteConfig,
        total_limit_watts: float | None,
    ) -> tuple[float | None, str | None, float | None, float | None, float | None]:
        """Resolve the best available current PV power estimate from live sensors."""
        battery_charge_watts = self._battery_charge_watts(live_inputs.battery_power_watts)
        if (
            battery_charge_watts is not None
            and site.battery_charge_limit_watts is not None
        ):
            battery_charge_watts = min(
                battery_charge_watts,
                site.battery_charge_limit_watts,
            )

        grid_import_watts, grid_export_watts = self._grid_flow_watts(
            live_inputs.grid_power_watts
        )

        if live_inputs.pv_power_watts is not None:
            effective_pv_power = max(live_inputs.pv_power_watts, 0.0)
            if total_limit_watts is not None:
                effective_pv_power = min(effective_pv_power, total_limit_watts)
            return (
                effective_pv_power,
                "pv_power_sensor",
                battery_charge_watts,
                grid_import_watts,
                grid_export_watts,
            )

        inverter_output_watts = (
            max(live_inputs.inverter_power_watts, 0.0)
            if live_inputs.inverter_power_watts is not None
            else None
        )
        if (
            inverter_output_watts is not None
            and site.grid_output_limit_watts is not None
        ):
            inverter_output_watts = min(inverter_output_watts, site.grid_output_limit_watts)

        battery_charge_from_pv_watts = battery_charge_watts
        interpretation = self._config.home_assistant.interpretation
        if (
            battery_charge_from_pv_watts is not None
            and interpretation.battery_charging_from_grid_possible
        ):
            battery_charge_from_pv_watts = max(
                battery_charge_from_pv_watts - (grid_import_watts or 0.0),
                0.0,
            )

        components = [
            value
            for value in (inverter_output_watts, battery_charge_from_pv_watts)
            if value is not None
        ]
        if not components:
            return (
                None,
                None,
                battery_charge_watts,
                grid_import_watts,
                grid_export_watts,
            )

        inferred_pv_power = sum(components)
        if total_limit_watts is not None:
            inferred_pv_power = min(inferred_pv_power, total_limit_watts)
        source = (
            "inverter_plus_battery"
            if battery_charge_from_pv_watts not in {None, 0.0}
            else "inverter_power_sensor"
        )
        return (
            inferred_pv_power,
            source,
            battery_charge_watts,
            grid_import_watts,
            grid_export_watts,
        )

    def _effective_total_limit_watts(
        self,
        *,
        site: SiteConfig,
        live_inputs: LiveInputs,
    ) -> float | None:
        """Resolve dynamic clipping limit based on battery state and config."""
        base_limit = site.effective_total_limit_watts()
        soc = live_inputs.battery_soc_percent
        full_threshold = self._config.engine.battery_full_soc_threshold
        full_limit = self._config.engine.limit_when_battery_full_watts
        if full_limit is None or soc is None or soc < full_threshold:
            return base_limit
        if base_limit is None:
            return full_limit
        return min(base_limit, full_limit)

    def _battery_charge_watts(self, battery_power_watts: float | None) -> float | None:
        """Normalize the configured battery power sensor to charge watts."""
        if battery_power_watts is None:
            return None

        sign_mode = self._config.home_assistant.interpretation.battery_power_sign
        if sign_mode == "positive_is_charging":
            return max(battery_power_watts, 0.0)
        return max(-battery_power_watts, 0.0)

    def _grid_flow_watts(
        self,
        grid_power_watts: float | None,
    ) -> tuple[float | None, float | None]:
        """Split grid power into import/export values."""
        if grid_power_watts is None:
            return (None, None)

        sign_mode = self._config.home_assistant.interpretation.grid_power_sign
        if sign_mode == "negative_is_import":
            return (
                max(-grid_power_watts, 0.0),
                max(grid_power_watts, 0.0),
            )

        return (
            max(grid_power_watts, 0.0),
            max(-grid_power_watts, 0.0),
        )

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
