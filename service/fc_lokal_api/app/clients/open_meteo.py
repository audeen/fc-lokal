"""Open-Meteo forecast client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ..config import OpenMeteoConfig
from ..models import PlaneConfig, SiteConfig, WeatherPoint

LOGGER = logging.getLogger(__name__)


class OpenMeteoClientError(Exception):
    """Raised when Open-Meteo data cannot be fetched reliably."""


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

        response = await self._request_with_retry(params=params)
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

    async def _request_with_retry(self, *, params: dict[str, object]) -> httpx.Response:
        """Call Open-Meteo with short retries for transient failures."""
        max_attempts = 3
        retry_delays = (0.4, 1.2)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._http.get(
                    self._config.base_url,
                    params=params,
                    timeout=self._config.timeout_seconds,
                )
                response.raise_for_status()
                return response
            except httpx.TimeoutException as err:
                last_error = err
                should_retry = attempt < max_attempts
                LOGGER.warning(
                    "Open-Meteo timeout on attempt %s/%s (%s)",
                    attempt,
                    max_attempts,
                    "retrying" if should_retry else "giving up",
                )
            except httpx.HTTPStatusError as err:
                last_error = err
                status = err.response.status_code if err.response is not None else None
                should_retry = attempt < max_attempts and status is not None and status >= 500
                LOGGER.warning(
                    "Open-Meteo returned HTTP %s on attempt %s/%s (%s)",
                    status,
                    attempt,
                    max_attempts,
                    "retrying" if should_retry else "giving up",
                )
                if not should_retry:
                    break
            except httpx.HTTPError as err:
                last_error = err
                should_retry = attempt < max_attempts
                LOGGER.warning(
                    "Open-Meteo transport error on attempt %s/%s (%s): %s",
                    attempt,
                    max_attempts,
                    "retrying" if should_retry else "giving up",
                    err,
                )

            if attempt < max_attempts:
                await asyncio.sleep(retry_delays[attempt - 1])

        raise OpenMeteoClientError(
            "Open-Meteo is temporarily unavailable"
        ) from last_error


def _parse_local_time(value: str, timezone: ZoneInfo) -> datetime:
    """Parse Open-Meteo local timestamps."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)
