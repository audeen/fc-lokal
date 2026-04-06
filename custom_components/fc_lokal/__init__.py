"""The FC Lokal integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .compat import get_plane_configs
from .const import (
    CONF_AZIMUTH,
    CONF_BASE_URL,
    CONF_DECLINATION,
    CONF_MODULES_POWER,
    CONF_SOURCE_MODE,
    DEFAULT_AZIMUTH,
    DEFAULT_DECLINATION,
    DEFAULT_MODULES_POWER,
    DOMAIN,
    SOURCE_MODE_FORECAST_SOLAR_API,
)
from .coordinator import ForecastSolarConfigEntry, ForecastSolarDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_migrate_entry(
    hass: HomeAssistant, entry: ForecastSolarConfigEntry
) -> bool:
    """Migrate old config entry."""
    if entry.version == 1:
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        if "modules power" in new_options:
            new_data[CONF_MODULES_POWER] = new_options.pop("modules power")
        if CONF_DECLINATION in new_options:
            new_data[CONF_DECLINATION] = new_options.pop(CONF_DECLINATION)
        if CONF_AZIMUTH in new_options:
            new_data[CONF_AZIMUTH] = new_options.pop(CONF_AZIMUTH)
        new_options["damping_morning"] = new_options.get("damping", 0.0)
        new_options["damping_evening"] = new_options.pop("damping", 0.0)
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2
        )

    if entry.version == 2:
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        new_data.setdefault(
            CONF_DECLINATION, new_options.pop(CONF_DECLINATION, DEFAULT_DECLINATION)
        )
        new_data.setdefault(CONF_AZIMUTH, new_options.pop(CONF_AZIMUTH, DEFAULT_AZIMUTH))
        new_data.setdefault(
            CONF_MODULES_POWER,
            new_options.pop(CONF_MODULES_POWER, DEFAULT_MODULES_POWER),
        )
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=3
        )

    if entry.version == 3:
        new_options = dict(entry.options)
        new_options.setdefault(CONF_SOURCE_MODE, SOURCE_MODE_FORECAST_SOLAR_API)
        new_options.setdefault(CONF_BASE_URL, "")
        hass.config_entries.async_update_entry(entry, options=new_options, version=4)

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ForecastSolarConfigEntry
) -> bool:
    """Set up FC Lokal from a config entry."""
    plane_configs = get_plane_configs(entry)
    if not plane_configs:
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="no_plane")

    source_mode = entry.options.get(CONF_SOURCE_MODE, SOURCE_MODE_FORECAST_SOLAR_API)
    if source_mode == SOURCE_MODE_FORECAST_SOLAR_API:
        if len(plane_configs) > 1 and not entry.options.get(CONF_API_KEY):
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="api_key_required",
            )
    elif not entry.options.get(CONF_BASE_URL):
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="base_url_required",
        )

    coordinator = ForecastSolarDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ForecastSolarConfigEntry
) -> None:
    """Handle config entry updates."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: ForecastSolarConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
