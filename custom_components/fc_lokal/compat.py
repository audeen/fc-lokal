"""Compatibility helpers for different Home Assistant versions."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import CONF_AZIMUTH, CONF_DECLINATION, CONF_MODULES_POWER, SUBENTRY_TYPE_PLANE

try:
    from homeassistant.config_entries import ConfigSubentryFlow

    HAS_CONFIG_SUBENTRIES = True
except ImportError:
    ConfigSubentryFlow = object
    HAS_CONFIG_SUBENTRIES = False


def get_plane_configs(entry: ConfigEntry) -> list[dict[str, int]]:
    """Return plane configuration for old and new entry formats."""
    if hasattr(entry, "get_subentries_of_type"):
        subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_PLANE)
        if subentries:
            return [
                {
                    CONF_DECLINATION: subentry.data[CONF_DECLINATION],
                    CONF_AZIMUTH: subentry.data[CONF_AZIMUTH],
                    CONF_MODULES_POWER: subentry.data[CONF_MODULES_POWER],
                }
                for subentry in subentries
            ]

    if all(
        key in entry.data
        for key in (CONF_DECLINATION, CONF_AZIMUTH, CONF_MODULES_POWER)
    ):
        return [
            {
                CONF_DECLINATION: entry.data[CONF_DECLINATION],
                CONF_AZIMUTH: entry.data[CONF_AZIMUTH],
                CONF_MODULES_POWER: entry.data[CONF_MODULES_POWER],
            }
        ]

    return []


def get_plane_count(entry: ConfigEntry) -> int:
    """Return the number of configured planes."""
    return len(get_plane_configs(entry))


def build_plane_title(plane: dict[str, Any]) -> str:
    """Build a readable plane title."""
    return (
        f"{plane[CONF_DECLINATION]}\N{DEGREE SIGN} / "
        f"{plane[CONF_AZIMUTH]}\N{DEGREE SIGN} / "
        f"{plane[CONF_MODULES_POWER]}W"
    )
