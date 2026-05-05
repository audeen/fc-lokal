"""Support for the FC Lokal sensor service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from forecast_solar.models import Estimate
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import ForecastSolarDataUpdateCoordinator


# Scope of the optional `forecast` extra-state-attribute exposed by some
# sensors. The attribute holds an array of {"period_start": iso, "value": n}
# dicts that custom Lovelace cards (e.g. statistics-graph-chart-card with
# `data_attribute: forecast`) can render directly.
FORECAST_SCOPE_TODAY_ENERGY = "today_energy"
FORECAST_SCOPE_TOMORROW_ENERGY = "tomorrow_energy"
FORECAST_SCOPE_FULL_POWER = "full_power"


@dataclass(frozen=True)
class ForecastSolarSensorEntityDescription(SensorEntityDescription):
    """Describes an FC Lokal sensor."""

    state: Callable[[Estimate], Any] | None = None
    forecast_scope: str | None = None


SENSORS: tuple[ForecastSolarSensorEntityDescription, ...] = (
    ForecastSolarSensorEntityDescription(
        key="energy_production_today",
        translation_key="energy_production_today",
        state=lambda estimate: estimate.energy_production_today,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        forecast_scope=FORECAST_SCOPE_TODAY_ENERGY,
    ),
    ForecastSolarSensorEntityDescription(
        key="energy_production_today_remaining",
        translation_key="energy_production_today_remaining",
        state=lambda estimate: estimate.energy_production_today_remaining,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    ForecastSolarSensorEntityDescription(
        key="energy_production_tomorrow",
        translation_key="energy_production_tomorrow",
        state=lambda estimate: estimate.energy_production_tomorrow,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        forecast_scope=FORECAST_SCOPE_TOMORROW_ENERGY,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_highest_peak_time_today",
        translation_key="power_highest_peak_time_today",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_highest_peak_time_tomorrow",
        translation_key="power_highest_peak_time_tomorrow",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_production_now",
        translation_key="power_production_now",
        device_class=SensorDeviceClass.POWER,
        state=lambda estimate: estimate.power_production_now,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        forecast_scope=FORECAST_SCOPE_FULL_POWER,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_production_next_hour",
        translation_key="power_production_next_hour",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=1)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_production_next_12hours",
        translation_key="power_production_next_12hours",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=12)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    ForecastSolarSensorEntityDescription(
        key="power_production_next_24hours",
        translation_key="power_production_next_24hours",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=24)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    ForecastSolarSensorEntityDescription(
        key="energy_current_hour",
        translation_key="energy_current_hour",
        state=lambda estimate: estimate.energy_current_hour,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    ForecastSolarSensorEntityDescription(
        key="energy_next_hour",
        translation_key="energy_next_hour",
        state=lambda estimate: estimate.sum_energy_production(1),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FC Lokal sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ForecastSolarSensorEntity(
            entry_id=entry.entry_id,
            coordinator=coordinator,
            entity_description=entity_description,
        )
        for entity_description in SENSORS
    )


class ForecastSolarSensorEntity(
    CoordinatorEntity[ForecastSolarDataUpdateCoordinator], SensorEntity
):
    """Defines an FC Lokal sensor."""

    entity_description: ForecastSolarSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry_id: str,
        coordinator: ForecastSolarDataUpdateCoordinator,
        entity_description: ForecastSolarSensorEntityDescription,
    ) -> None:
        """Initialize FC Lokal sensor."""
        super().__init__(coordinator=coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{entry_id}_{entity_description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="FC Lokal",
            model=getattr(getattr(coordinator.data, "account_type", None), "value", "custom"),
            name="FC Lokal solar forecast",
            configuration_url=coordinator.config_entry.options.get(CONF_BASE_URL)
            or "https://forecast.solar",
        )

    @property
    def native_value(self) -> datetime | StateType:
        """Return the state of the sensor."""
        if self.entity_description.state is None:
            state: StateType | datetime = getattr(
                self.coordinator.data, self.entity_description.key
            )
        else:
            state = self.entity_description.state(self.coordinator.data)
        return state

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the hourly forecast curve for selected sensors.

        The attribute name (`forecast`) and item shape
        (`{"period_start": iso, "value": number}`) follow the de-facto
        Solcast convention so that custom Lovelace cards such as
        statistics-graph-chart-card (`data_attribute: forecast`) and
        apexcharts-card can render the future curve directly without
        relying on the HA recorder history.
        """
        scope = self.entity_description.forecast_scope
        if scope is None:
            return None

        estimate = self.coordinator.data
        if estimate is None:
            return None

        if scope == FORECAST_SCOPE_FULL_POWER:
            source = getattr(estimate, "watts", None)
            unit = "W"
        elif scope in (
            FORECAST_SCOPE_TODAY_ENERGY,
            FORECAST_SCOPE_TOMORROW_ENERGY,
        ):
            source = getattr(estimate, "wh_period", None)
            unit = "Wh"
        else:
            return None

        if not source:
            return None

        target_day: date | None = None
        if scope == FORECAST_SCOPE_TODAY_ENERGY:
            target_day = estimate.now().date()
        elif scope == FORECAST_SCOPE_TOMORROW_ENERGY:
            target_day = estimate.now().date() + timedelta(days=1)

        forecast: list[dict[str, Any]] = []
        for timestamp, value in sorted(source.items()):
            if target_day is not None and timestamp.date() != target_day:
                continue
            forecast.append(
                {
                    "period_start": timestamp.isoformat(),
                    "value": value,
                }
            )

        if not forecast:
            return None

        return {"forecast": forecast, "forecast_unit": unit}
