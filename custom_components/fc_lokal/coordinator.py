"""DataUpdateCoordinator for the FC Lokal integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from forecast_solar import Estimate, ForecastSolar, ForecastSolarConnectionError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    ForecastSolarCustomClient,
    ForecastSolarCustomClientConfig,
    ForecastSolarCustomClientError,
)
from .compat import get_plane_configs
from .const import (
    CONF_ACTUAL_SENSOR_ENTITY_ID,
    CONF_AZIMUTH,
    CONF_BASE_URL,
    CONF_DAMPING_EVENING,
    CONF_DAMPING_MORNING,
    CONF_DECLINATION,
    CONF_INVERTER_SIZE,
    CONF_MODULES_POWER,
    CONF_REQUEST_TIMEOUT,
    CONF_SOURCE_MODE,
    CONF_USE_LIVE_ACTUAL,
    DEFAULT_DAMPING,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SOURCE_MODE,
    DOMAIN,
    LOGGER,
    SOURCE_MODE_CUSTOM_API,
    SOURCE_MODE_FORECAST_SOLAR_API,
)

try:
    from forecast_solar import Plane as ForecastSolarPlane
except ImportError:
    ForecastSolarPlane = None


class ForecastProvider(Protocol):
    """Protocol shared by cloud and custom providers."""

    async def estimate(self, *, actual: float | None = None) -> Estimate:
        """Return forecast data."""


class ForecastSolarDataUpdateCoordinator(DataUpdateCoordinator[Estimate]):
    """The FC Lokal Data Update Coordinator."""

    config_entry: "ForecastSolarConfigEntry"
    forecast: ForecastProvider

    def __init__(self, hass: HomeAssistant, entry: "ForecastSolarConfigEntry") -> None:
        """Initialize the FC Lokal coordinator."""
        api_key = entry.options.get(CONF_API_KEY) or None
        source_mode = entry.options.get(CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE)
        request_timeout = entry.options.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)

        inverter_size: float | None = entry.options.get(CONF_INVERTER_SIZE)
        if inverter_size is not None and inverter_size > 0:
            inverter_size = inverter_size / 1000

        plane_configs = get_plane_configs(entry)
        main_plane = plane_configs[0]
        extra_plane_dicts = [
            {
                "declination": plane_config[CONF_DECLINATION],
                "azimuth": (plane_config[CONF_AZIMUTH] - 180),
                "kwp": (plane_config[CONF_MODULES_POWER] / 1000),
            }
            for plane_config in plane_configs[1:]
        ]
        forecast_solar_planes = []
        if ForecastSolarPlane is not None:
            forecast_solar_planes = [
                ForecastSolarPlane(**plane_config) for plane_config in extra_plane_dicts
            ]
        elif extra_plane_dicts:
            LOGGER.warning(
                "Installed forecast_solar package does not expose Plane; "
                "additional planes are only forwarded in custom_api mode"
            )

        session = async_get_clientsession(hass)
        if source_mode == SOURCE_MODE_CUSTOM_API:
            self.forecast = ForecastSolarCustomClient(
                session=session,
                base_url=entry.options[CONF_BASE_URL],
                request_timeout=request_timeout,
                config=ForecastSolarCustomClientConfig(
                    latitude=entry.data[CONF_LATITUDE],
                    longitude=entry.data[CONF_LONGITUDE],
                    declination=main_plane[CONF_DECLINATION],
                    azimuth=(main_plane[CONF_AZIMUTH] - 180),
                    kwp=(main_plane[CONF_MODULES_POWER] / 1000),
                    damping_morning=entry.options.get(
                        CONF_DAMPING_MORNING, DEFAULT_DAMPING
                    ),
                    damping_evening=entry.options.get(
                        CONF_DAMPING_EVENING, DEFAULT_DAMPING
                    ),
                    inverter=inverter_size,
                    planes=extra_plane_dicts,
                ),
            )
        else:
            self.forecast = ForecastSolar(
                api_key=api_key,
                session=session,
                latitude=entry.data[CONF_LATITUDE],
                longitude=entry.data[CONF_LONGITUDE],
                declination=main_plane[CONF_DECLINATION],
                azimuth=(main_plane[CONF_AZIMUTH] - 180),
                kwp=(main_plane[CONF_MODULES_POWER] / 1000),
                damping_morning=entry.options.get(CONF_DAMPING_MORNING, DEFAULT_DAMPING),
                damping_evening=entry.options.get(CONF_DAMPING_EVENING, DEFAULT_DAMPING),
                inverter=inverter_size,
                planes=forecast_solar_planes,
            )

        update_interval = timedelta(hours=1)
        if source_mode == SOURCE_MODE_CUSTOM_API:
            update_interval = timedelta(minutes=15)
        elif api_key is not None:
            update_interval = timedelta(minutes=30)

        LOGGER.debug(
            "Initializing FC Lokal coordinator with source_mode=%s, planes=%s, update_interval=%s",
            source_mode,
            len(plane_configs),
            update_interval,
        )

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Estimate:
        """Fetch FC Lokal estimates."""
        source_mode = self.config_entry.options.get(CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE)

        try:
            if source_mode == SOURCE_MODE_CUSTOM_API:
                actual = self._get_live_actual()
                LOGGER.debug("Fetching forecast via custom API with actual=%s", actual)
                return await self.forecast.estimate(actual=actual)

            LOGGER.debug("Fetching forecast via Forecast.Solar cloud API")
            return await self.forecast.estimate()
        except ForecastSolarConnectionError as error:
            raise UpdateFailed(error) from error
        except ForecastSolarCustomClientError as error:
            raise UpdateFailed(error) from error

    def _get_live_actual(self) -> float | None:
        """Read the optional live actual value from a Home Assistant entity."""
        if not self.config_entry.options.get(CONF_USE_LIVE_ACTUAL, False):
            return None

        entity_id = self.config_entry.options.get(CONF_ACTUAL_SENSOR_ENTITY_ID)
        if not entity_id:
            LOGGER.debug("Live actual is enabled but no entity_id is configured")
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            LOGGER.debug("Configured live actual entity %s was not found", entity_id)
            return None

        if state.state in {"unknown", "unavailable"}:
            LOGGER.debug(
                "Configured live actual entity %s has unusable state %s",
                entity_id,
                state.state,
            )
            return None

        try:
            return float(state.state)
        except ValueError:
            LOGGER.debug(
                "Configured live actual entity %s returned non-numeric state %s",
                entity_id,
                state.state,
            )
            return None


ForecastSolarConfigEntry = ConfigEntry[ForecastSolarDataUpdateCoordinator]
