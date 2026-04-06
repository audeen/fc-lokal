"""Config flow for FC Lokal integration."""

from __future__ import annotations

import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .compat import get_plane_count
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
    DEFAULT_AZIMUTH,
    DEFAULT_DAMPING,
    DEFAULT_DECLINATION,
    DEFAULT_MODULES_POWER,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SOURCE_MODE,
    DOMAIN,
    SOURCE_MODE_CUSTOM_API,
    SOURCE_MODE_FORECAST_SOLAR_API,
)

RE_API_KEY = re.compile(r"^[a-zA-Z0-9]{16}$")

PLANE_SCHEMA = {
    vol.Required(CONF_DECLINATION, default=DEFAULT_DECLINATION): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=90)
    ),
    vol.Required(CONF_AZIMUTH, default=DEFAULT_AZIMUTH): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=360)
    ),
    vol.Required(CONF_MODULES_POWER, default=DEFAULT_MODULES_POWER): vol.All(
        vol.Coerce(int), vol.Range(min=1)
    ),
}


class ForecastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FC Lokal."""

    VERSION = 4

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Get the options flow for this handler."""
        return ForecastSolarOptionFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_LATITUDE: user_input[CONF_LATITUDE],
                    CONF_LONGITUDE: user_input[CONF_LONGITUDE],
                    CONF_DECLINATION: user_input[CONF_DECLINATION],
                    CONF_AZIMUTH: user_input[CONF_AZIMUTH],
                    CONF_MODULES_POWER: user_input[CONF_MODULES_POWER],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self.hass.config.location_name): str,
                    vol.Required(CONF_LATITUDE, default=self.hass.config.latitude): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE, default=self.hass.config.longitude
                    ): cv.longitude,
                    **PLANE_SCHEMA,
                }
            ),
        )


class ForecastSolarOptionFlowHandler(OptionsFlow):
    """Handle options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        selected_source_mode = self.config_entry.options.get(
            CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE
        )

        if user_input is not None:
            source_mode = user_input.get(CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE)
            selected_source_mode = source_mode
            planes_count = get_plane_count(self.config_entry)
            api_key = (user_input.get(CONF_API_KEY) or "").strip() or None
            base_url = (user_input.get(CONF_BASE_URL) or "").strip().rstrip("/")
            use_live_actual = user_input.get(CONF_USE_LIVE_ACTUAL, False)
            actual_sensor_entity_id = (
                user_input.get(CONF_ACTUAL_SENSOR_ENTITY_ID) or ""
            ).strip()

            if (
                source_mode == SOURCE_MODE_FORECAST_SOLAR_API
                and planes_count > 1
                and not api_key
            ):
                errors[CONF_API_KEY] = "api_key_required"
            elif api_key and RE_API_KEY.match(api_key) is None:
                errors[CONF_API_KEY] = "invalid_api_key"
            elif source_mode == SOURCE_MODE_CUSTOM_API and not base_url:
                errors[CONF_BASE_URL] = "base_url_required"
            elif source_mode == SOURCE_MODE_CUSTOM_API:
                try:
                    cv.url(base_url)
                except vol.Invalid:
                    errors[CONF_BASE_URL] = "invalid_base_url"

            if use_live_actual and not actual_sensor_entity_id:
                errors[CONF_ACTUAL_SENSOR_ENTITY_ID] = "actual_sensor_entity_id_required"

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SOURCE_MODE: source_mode,
                        CONF_API_KEY: api_key,
                        CONF_BASE_URL: base_url,
                        CONF_DAMPING_MORNING: user_input.get(
                            CONF_DAMPING_MORNING, DEFAULT_DAMPING
                        ),
                        CONF_DAMPING_EVENING: user_input.get(
                            CONF_DAMPING_EVENING, DEFAULT_DAMPING
                        ),
                        CONF_INVERTER_SIZE: user_input.get(CONF_INVERTER_SIZE),
                        CONF_REQUEST_TIMEOUT: user_input.get(
                            CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT
                        ),
                        CONF_USE_LIVE_ACTUAL: use_live_actual,
                        CONF_ACTUAL_SENSOR_ENTITY_ID: actual_sensor_entity_id,
                    },
                )

        planes_count = get_plane_count(self.config_entry)
        suggested_api_key = self.config_entry.options.get(CONF_API_KEY, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SOURCE_MODE, default=selected_source_mode
                    ): vol.In(
                        [SOURCE_MODE_FORECAST_SOLAR_API, SOURCE_MODE_CUSTOM_API]
                    ),
                    (
                        vol.Required(CONF_API_KEY, default=suggested_api_key)
                        if (
                            planes_count > 1
                            and selected_source_mode == SOURCE_MODE_FORECAST_SOLAR_API
                        )
                        else vol.Optional(CONF_API_KEY, default=suggested_api_key)
                    ): str,
                    vol.Optional(
                        CONF_BASE_URL,
                        default=self.config_entry.options.get(CONF_BASE_URL, ""),
                    ): str,
                    vol.Optional(
                        CONF_DAMPING_MORNING,
                        default=self.config_entry.options.get(
                            CONF_DAMPING_MORNING, DEFAULT_DAMPING
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
                    vol.Optional(
                        CONF_DAMPING_EVENING,
                        default=self.config_entry.options.get(
                            CONF_DAMPING_EVENING, DEFAULT_DAMPING
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
                    vol.Optional(
                        CONF_INVERTER_SIZE,
                        default=self.config_entry.options.get(CONF_INVERTER_SIZE),
                    ): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1))),
                    vol.Required(
                        CONF_REQUEST_TIMEOUT,
                        default=self.config_entry.options.get(
                            CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                    vol.Required(
                        CONF_USE_LIVE_ACTUAL,
                        default=self.config_entry.options.get(CONF_USE_LIVE_ACTUAL, False),
                    ): bool,
                    vol.Optional(
                        CONF_ACTUAL_SENSOR_ENTITY_ID,
                        default=self.config_entry.options.get(
                            CONF_ACTUAL_SENSOR_ENTITY_ID, ""
                        ),
                    ): str,
                }
            ),
            errors=errors,
        )
