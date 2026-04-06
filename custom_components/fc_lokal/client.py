"""Client for custom Forecast.Solar-compatible endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from forecast_solar import Estimate
from yarl import URL

from .const import LOGGER


class ForecastSolarCustomClientError(Exception):
    """Base exception for the custom Forecast.Solar client."""


class ForecastSolarCustomClientConnectionError(ForecastSolarCustomClientError):
    """Raised when the custom endpoint cannot be reached."""


class ForecastSolarCustomClientResponseError(ForecastSolarCustomClientError):
    """Raised when the custom endpoint returns invalid data."""


@dataclass(slots=True)
class ForecastSolarCustomClientConfig:
    """Configuration passed to the custom endpoint."""

    latitude: float
    longitude: float
    declination: int
    azimuth: int
    kwp: float
    damping_morning: float
    damping_evening: float
    inverter: float | None
    planes: list[dict[str, float | int]]


class ForecastSolarCustomClient:
    """HTTP client for a local Forecast.Solar-compatible endpoint."""

    def __init__(
        self,
        *,
        session: ClientSession,
        base_url: str,
        request_timeout: int,
        config: ForecastSolarCustomClientConfig,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout
        self._config = config

    async def estimate(self, *, actual: float | None = None) -> Estimate:
        """Fetch an estimate from the custom endpoint."""
        url = URL(f"{self._base_url}/estimate")
        params = self._build_query_params(actual=actual)

        LOGGER.debug(
            "Requesting custom Forecast.Solar estimate from %s with params keys=%s",
            url,
            sorted(params),
        )

        try:
            async with self._session.get(
                url,
                params=params,
                timeout=ClientTimeout(total=self._request_timeout),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except TimeoutError as err:
            raise ForecastSolarCustomClientConnectionError(
                f"Timed out after {self._request_timeout}s while requesting {url}"
            ) from err
        except ClientResponseError as err:
            raise ForecastSolarCustomClientResponseError(
                f"Custom endpoint returned HTTP {err.status} for {url}"
            ) from err
        except ClientError as err:
            raise ForecastSolarCustomClientConnectionError(
                f"Could not connect to custom endpoint {url}: {err}"
            ) from err
        except ValueError as err:
            raise ForecastSolarCustomClientResponseError(
                f"Custom endpoint {url} returned invalid JSON"
            ) from err

        if not isinstance(payload, dict):
            raise ForecastSolarCustomClientResponseError(
                f"Custom endpoint {url} returned a non-object JSON payload"
            )

        try:
            estimate = Estimate.from_dict(payload)
        except Exception as err:
            raise ForecastSolarCustomClientResponseError(
                "Custom endpoint payload could not be parsed as Forecast.Solar data"
            ) from err

        LOGGER.debug(
            "Received custom Forecast.Solar payload with timezone=%s and rate_limit=%s",
            getattr(estimate, "timezone", None),
            getattr(estimate, "api_rate_limit", None),
        )
        return estimate

    def _build_query_params(self, *, actual: float | None) -> dict[str, str | float | int]:
        """Build query parameters for the custom endpoint."""
        params: dict[str, str | float | int] = {
            "latitude": self._config.latitude,
            "longitude": self._config.longitude,
            "declination": self._config.declination,
            "azimuth": self._config.azimuth,
            "kwp": self._config.kwp,
            "damping_morning": self._config.damping_morning,
            "damping_evening": self._config.damping_evening,
        }

        if self._config.inverter is not None:
            params["inverter"] = self._config.inverter

        for index, plane in enumerate(self._config.planes, start=2):
            params[f"plane_{index}_declination"] = int(plane["declination"])
            params[f"plane_{index}_azimuth"] = int(plane["azimuth"])
            params[f"plane_{index}_kwp"] = float(plane["kwp"])

        if actual is not None:
            params["actual"] = actual

        return params
