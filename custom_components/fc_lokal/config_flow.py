"""Config flow for FC Lokal integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector

from .compat import ConfigSubentryFlow, HAS_CONFIG_SUBENTRIES, get_plane_count
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

PLANE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DECLINATION): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=90, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(CONF_AZIMUTH): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=360, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(CONF_MODULES_POWER): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Coerce(int),
        ),
    }
)


class ForecastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FC Lokal."""

    VERSION = 4

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "ForecastSolarOptionFlowHandler":
        """Get the options flow for this handler."""
        return ForecastSolarOptionFlowHandler()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        if not HAS_CONFIG_SUBENTRIES:
            return {}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_NAME): str,
                        vol.Required(CONF_LATITUDE): cv.latitude,
                        vol.Required(CONF_LONGITUDE): cv.longitude,
                    }
                ).extend(PLANE_SCHEMA.schema),
                {
                    CONF_NAME: self.hass.config.location_name,
                    CONF_LATITUDE: self.hass.config.latitude,
                    CONF_LONGITUDE: self.hass.config.longitude,
                    CONF_DECLINATION: DEFAULT_DECLINATION,
                    CONF_AZIMUTH: DEFAULT_AZIMUTH,
                    CONF_MODULES_POWER: DEFAULT_MODULES_POWER,
                },
            ),
        )


class ForecastSolarOptionFlowHandler(OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        selected_source_mode = self.config_entry.options.get(
            CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE
        )

        if user_input is not None:
            source_mode = user_input.get(CONF_SOURCE_MODE, DEFAULT_SOURCE_MODE)
            selected_source_mode = source_mode
            planes_count = get_plane_count(self.config_entry)
            api_key = user_input.get(CONF_API_KEY) or None
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
                    data=user_input
                    | {
                        CONF_API_KEY: api_key,
                        CONF_BASE_URL: base_url,
                        CONF_ACTUAL_SENSOR_ENTITY_ID: actual_sensor_entity_id,
                    },
                )

        planes_count = get_plane_count(self.config_entry)
        suggested_api_key = self.config_entry.options.get(CONF_API_KEY, "")

        schema: dict[vol.Marker, Any] = {
            vol.Required(
                CONF_SOURCE_MODE, default=selected_source_mode
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=SOURCE_MODE_FORECAST_SOLAR_API,
                            label="Forecast.Solar API",
                        ),
                        selector.SelectOptionDict(
                            value=SOURCE_MODE_CUSTOM_API,
                            label="Custom API",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            (
                vol.Required(CONF_API_KEY, default=suggested_api_key)
                if (
                    planes_count > 1
                    and selected_source_mode == SOURCE_MODE_FORECAST_SOLAR_API
                )
                else vol.Optional(
                    CONF_API_KEY,
                    description={"suggested_value": suggested_api_key},
                )
            ): str,
            vol.Optional(
                CONF_BASE_URL,
                description={
                    "suggested_value": self.config_entry.options.get(CONF_BASE_URL, "")
                },
            ): str,
            vol.Optional(
                CONF_DAMPING_MORNING,
                default=self.config_entry.options.get(
                    CONF_DAMPING_MORNING, DEFAULT_DAMPING
                ),
            ): vol.All(
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=1,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Coerce(float),
            ),
            vol.Optional(
                CONF_DAMPING_EVENING,
                default=self.config_entry.options.get(
                    CONF_DAMPING_EVENING, DEFAULT_DAMPING
                ),
            ): vol.All(
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=1,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Coerce(float),
            ),
            vol.Optional(
                CONF_INVERTER_SIZE,
                description={
                    "suggested_value": self.config_entry.options.get(CONF_INVERTER_SIZE)
                },
            ): vol.All(
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Coerce(int),
            ),
            vol.Required(
                CONF_REQUEST_TIMEOUT,
                default=self.config_entry.options.get(
                    CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT
                ),
            ): vol.All(
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Coerce(int),
            ),
            vol.Required(
                CONF_USE_LIVE_ACTUAL,
                default=self.config_entry.options.get(CONF_USE_LIVE_ACTUAL, False),
            ): bool,
            vol.Optional(
                CONF_ACTUAL_SENSOR_ENTITY_ID,
                description={
                    "suggested_value": self.config_entry.options.get(
                        CONF_ACTUAL_SENSOR_ENTITY_ID, ""
                    )
                },
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
