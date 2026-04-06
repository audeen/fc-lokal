"""Home Assistant API client."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import HomeAssistantConfig
from ..models import LiveInputs


class HomeAssistantClient:
    """Very small async client for the Home Assistant REST API."""

    def __init__(self, *, http_client: httpx.AsyncClient, config: HomeAssistantConfig) -> None:
        """Initialize the client."""
        self._http = http_client
        self._config = config

    async def fetch_live_inputs(self) -> LiveInputs:
        """Fetch the configured live inputs from Home Assistant."""
        sensors = self._config.sensors
        return LiveInputs(
            pv_power_watts=await self._read_power_sensor(sensors.pv_power_entity_id),
            pv_energy_today_wh=await self._read_energy_sensor(
                sensors.pv_energy_today_entity_id
            ),
            inverter_power_watts=await self._read_power_sensor(
                sensors.inverter_power_entity_id
            ),
            grid_power_watts=await self._read_power_sensor(sensors.grid_power_entity_id),
            battery_power_watts=await self._read_power_sensor(
                sensors.battery_power_entity_id
            ),
        )

    async def fetch_state(self, entity_id: str) -> dict[str, Any] | None:
        """Fetch a single Home Assistant entity state."""
        if not entity_id:
            return None

        response = await self._http.get(
            f"{self._config.base_url}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {self._config.token}"},
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    async def _read_power_sensor(self, entity_id: str | None) -> float | None:
        """Read a power value and normalize it to watts."""
        if not entity_id:
            return None
        state = await self.fetch_state(entity_id)
        return self._normalize_power_watts(state)

    async def _read_energy_sensor(self, entity_id: str | None) -> float | None:
        """Read an energy value and normalize it to watt-hours."""
        if not entity_id:
            return None
        state = await self.fetch_state(entity_id)
        return self._normalize_energy_wh(state)

    @staticmethod
    def _normalize_power_watts(state: dict[str, Any] | None) -> float | None:
        """Normalize a Home Assistant power state to watts."""
        value = HomeAssistantClient._parse_numeric_state(state)
        if value is None:
            return None

        unit = str((state or {}).get("attributes", {}).get("unit_of_measurement", "W"))
        unit = unit.lower()
        if unit == "kw":
            return value * 1000
        return value

    @staticmethod
    def _normalize_energy_wh(state: dict[str, Any] | None) -> float | None:
        """Normalize a Home Assistant energy state to watt-hours."""
        value = HomeAssistantClient._parse_numeric_state(state)
        if value is None:
            return None

        unit = str((state or {}).get("attributes", {}).get("unit_of_measurement", "Wh"))
        unit = unit.lower()
        if unit == "kwh":
            return value * 1000
        if unit == "mwh":
            return value * 1_000_000
        return value

    @staticmethod
    def _parse_numeric_state(state: dict[str, Any] | None) -> float | None:
        """Parse a Home Assistant numeric state."""
        if not state:
            return None
        raw = state.get("state")
        if raw in {None, "unknown", "unavailable"}:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
