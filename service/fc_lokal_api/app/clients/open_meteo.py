"""Open-Meteo forecast client."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ..config import OpenMeteoConfig
from ..models import PlaneConfig, SiteConfig, WeatherPoint


class OpenMeteoClient:
    """Client for Open-Meteo's forecast API."""

    def __init__(self, *, http_client: httpx.AsyncClient, config: OpenMeteoConfig) -> None:
        """Initialize the client."""
        self._http = http_client
        self._config = config

    async def fetch_plane_forecast(
        self, *, site: SiteConfig, plane: PlaneConfig
    ) -> list[WeatherPoint]:
        """Fetch hourly GTI data for one plane."""
        params = {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "hourly": "global_tilted_irradiance,temperature_2m,cloud_cover",
            "forecast_days": self._config.forecast_days,
            "timezone": site.timezone,
            "tilt": plane.declination,
            "azimuth": plane.open_meteo_azimuth(),
        }
        if self._config.model and self._config.model != "best_match":
            params["models"] = self._config.model

        response = await self._http.get(
            self._config.base_url,
            params=params,
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        hourly = payload["hourly"]
        timezone = ZoneInfo(site.timezone)
        return [
            WeatherPoint(
                timestamp=_parse_local_time(timestamp, timezone),
                global_tilted_irradiance=float(gti or 0.0),
                temperature_c=(
                    float(hourly["temperature_2m"][index])
                    if hourly.get("temperature_2m", [None])[index] is not None
                    else None
                ),
                cloud_cover=(
                    float(hourly["cloud_cover"][index])
                    if hourly.get("cloud_cover", [None])[index] is not None
                    else None
                ),
            )
            for index, (timestamp, gti) in enumerate(
                zip(hourly["time"], hourly["global_tilted_irradiance"], strict=True)
            )
        ]


def _parse_local_time(value: str, timezone: ZoneInfo) -> datetime:
    """Parse Open-Meteo local timestamps."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)
