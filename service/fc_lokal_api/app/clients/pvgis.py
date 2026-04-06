"""PVGIS client scaffold."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from ..config import PVGISConfig
from ..models import PVGISPlaneBaseline, PlaneConfig, SiteConfig


class PVGISClient:
    """Tiny client for the official PVGIS API."""

    def __init__(self, *, http_client: httpx.AsyncClient, config: PVGISConfig) -> None:
        """Initialize the client."""
        self._http = http_client
        self._config = config
        self._baseline_cache: dict[
            tuple[float, float, float, int, int],
            PVGISPlaneBaseline,
        ] = {}

    async def fetch_baseline(self, *, site: SiteConfig, plane: PlaneConfig) -> dict[str, Any]:
        """Fetch a PVGIS baseline result for one plane."""
        return (await self.fetch_plane_baseline(site=site, plane=plane)).raw_payload

    async def fetch_plane_baseline(
        self, *, site: SiteConfig, plane: PlaneConfig
    ) -> PVGISPlaneBaseline:
        """Fetch and parse a PVGIS baseline result for one plane."""
        cache_key = self._cache_key(site=site, plane=plane)
        cached = self._baseline_cache.get(cache_key)
        if cached is not None:
            return cached

        response = await self._http.get(
            self._config.base_url,
            params=self._request_params(site=site, plane=plane),
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()

        baseline = self._parse_baseline(
            payload=response.json(),
            plane=plane,
        )
        self._baseline_cache[cache_key] = baseline
        return baseline

    def _request_params(self, *, site: SiteConfig, plane: PlaneConfig) -> dict[str, Any]:
        """Build the request parameters for one PVGIS query."""
        return {
            "lat": site.latitude,
            "lon": site.longitude,
            "peakpower": plane.kwp,
            "loss": self._config.loss_percent,
            "angle": plane.declination,
            "aspect": plane.pvgis_aspect(),
            "pvtechchoice": self._config.pvtechchoice,
            "mountingplace": self._config.mountingplace,
            "usehorizon": int(self._config.usehorizon),
            "outputformat": "json",
        }

    def _cache_key(
        self, *, site: SiteConfig, plane: PlaneConfig
    ) -> tuple[float, float, float, int, int]:
        """Build a stable in-memory cache key for immutable PVGIS baselines."""
        return (
            round(site.latitude, 6),
            round(site.longitude, 6),
            round(plane.kwp, 4),
            plane.declination,
            plane.pvgis_aspect(),
        )

    def _parse_baseline(
        self, *, payload: dict[str, Any], plane: PlaneConfig
    ) -> PVGISPlaneBaseline:
        """Parse the PVGIS JSON payload into a typed baseline summary."""
        monthly_daily_energy_kwh: dict[int, float] = {}
        monthly_energy_kwh: dict[int, float] = {}

        for entry in self._monthly_entries(payload):
            month = self._as_int(entry.get("month"))
            if month is None:
                continue

            daily_energy_kwh = self._as_float(entry.get("E_d"))
            if daily_energy_kwh is not None:
                monthly_daily_energy_kwh[month] = daily_energy_kwh

            month_energy_kwh = self._as_float(entry.get("E_m"))
            if month_energy_kwh is not None:
                monthly_energy_kwh[month] = month_energy_kwh

        totals = self._fixed_totals(payload)
        return PVGISPlaneBaseline(
            plane_name=plane.name,
            monthly_daily_energy_kwh=monthly_daily_energy_kwh,
            monthly_energy_kwh=monthly_energy_kwh,
            annual_energy_kwh=self._as_float(totals.get("E_y")),
            raw_payload=payload,
        )

    def _monthly_entries(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract monthly fixed-plane entries from a PVGIS response."""
        fixed = payload.get("outputs", {}).get("monthly", {}).get("fixed", [])
        if isinstance(fixed, list):
            return [entry for entry in fixed if isinstance(entry, dict)]
        if isinstance(fixed, dict):
            if "month" in fixed:
                return [fixed]
            for key in ("values", "data", "items"):
                nested = fixed.get(key)
                if isinstance(nested, list):
                    return [entry for entry in nested if isinstance(entry, dict)]
        return []

    def _fixed_totals(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract total fixed-plane values from a PVGIS response."""
        fixed = payload.get("outputs", {}).get("totals", {}).get("fixed", {})
        if isinstance(fixed, dict):
            if "E_y" in fixed or "E_d" in fixed:
                return fixed
            for key in ("values", "data", "items"):
                nested = fixed.get(key)
                if isinstance(nested, dict):
                    return nested
                if isinstance(nested, Iterable):
                    for item in nested:
                        if isinstance(item, dict) and ("E_y" in item or "E_d" in item):
                            return item
            return {}
        if isinstance(fixed, list):
            for entry in fixed:
                if isinstance(entry, dict) and ("E_y" in entry or "E_d" in entry):
                    return entry
        return {}

    @staticmethod
    def _as_float(value: Any) -> float | None:
        """Convert a PVGIS value to float when possible."""
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        """Convert a PVGIS value to int when possible."""
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
