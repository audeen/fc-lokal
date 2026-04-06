"""Constants for the FC Lokal integration."""

from __future__ import annotations

import logging

DOMAIN = "fc_lokal"
LOGGER = logging.getLogger(__package__)

CONF_DECLINATION = "declination"
CONF_AZIMUTH = "azimuth"
CONF_MODULES_POWER = "modules_power"
CONF_DAMPING = "damping"
CONF_DAMPING_MORNING = "damping_morning"
CONF_DAMPING_EVENING = "damping_evening"
CONF_INVERTER_SIZE = "inverter_size"
CONF_SOURCE_MODE = "source_mode"
CONF_BASE_URL = "base_url"
CONF_USE_LIVE_ACTUAL = "use_live_actual"
CONF_ACTUAL_SENSOR_ENTITY_ID = "actual_sensor_entity_id"
CONF_REQUEST_TIMEOUT = "request_timeout"

SOURCE_MODE_FORECAST_SOLAR_API = "forecast_solar_api"
SOURCE_MODE_CUSTOM_API = "custom_api"

DEFAULT_DECLINATION = 25
DEFAULT_AZIMUTH = 180
DEFAULT_MODULES_POWER = 10000
DEFAULT_DAMPING = 0.0
DEFAULT_SOURCE_MODE = SOURCE_MODE_FORECAST_SOLAR_API
DEFAULT_REQUEST_TIMEOUT = 10

MAX_PLANES = 4
SUBENTRY_TYPE_PLANE = "plane"
