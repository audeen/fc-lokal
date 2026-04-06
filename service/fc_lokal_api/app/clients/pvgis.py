"""PVGIS client scaffold."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import PVGISConfig
from ..models import PlaneConfig, SiteConfig


class PVGISClient:
    """Tiny client for the official PVGIS API."""

    def __init__(self, *, http_client: httpx.AsyncClient, config: PVGISConfig) -> None:
        """Initialize the client."""
        self._http = http_client
        self._config = config

    async def fetch_baseline(self, *, site: SiteConfig, plane: PlaneConfig) -> dict[str, Any]:
        """Fetch a PVGIS baseline result for one plane."""
        params = {
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

        response = await self._http.get(
            self._config.base_url,
            params=params,
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
