"""FastAPI entrypoint for the FC Lokal API service."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query, Request

from .clients.ha import HomeAssistantClient
from .clients.open_meteo import OpenMeteoClient
from .clients.pvgis import PVGISClient
from .config import AppConfig, load_config
from .engine import ForecastEngine
from .live_console import run_live_console, summarize_estimate_payload
from .models import EstimateRequest, PlaneConfig

CONFIG_PATH = os.getenv("FC_LOKAL_CONFIG", "/data/config.yaml")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the app service container."""
    config: AppConfig = load_config(CONFIG_PATH)
    public_http = httpx.AsyncClient()
    ha_http = httpx.AsyncClient(verify=config.home_assistant.verify_ssl)

    ha_client = (
        HomeAssistantClient(http_client=ha_http, config=config.home_assistant)
        if config.home_assistant.enabled
        else None
    )
    weather_client = OpenMeteoClient(http_client=public_http, config=config.open_meteo)
    pvgis_client = (
        PVGISClient(http_client=public_http, config=config.pvgis)
        if config.pvgis.enabled
        else None
    )

    app.state.config = config
    app.state.public_http = public_http
    app.state.ha_http = ha_http
    app.state.engine = ForecastEngine(
        config=config,
        weather_client=weather_client,
        ha_client=ha_client,
        pvgis_client=pvgis_client,
    )
    app.state.last_estimate_meta = None

    live_task: asyncio.Task[None] | None = None
    if _env_truthy("FC_LOKAL_LIVE_CONSOLE"):
        print(
            "fc-lokal-api: live console enabled (Rich); requires container TTY — use tty: true in docker-compose",
            flush=True,
        )
        live_task = asyncio.create_task(run_live_console(app))

    try:
        yield
    finally:
        if live_task:
            live_task.cancel()
            try:
                await live_task
            except asyncio.CancelledError:
                pass
        await public_http.aclose()
        await ha_http.aclose()


app = FastAPI(title="FC Lokal API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Return service health information."""
    return await app.state.engine.build_health()


@app.get("/estimate")
async def estimate(
    request: Request,
    actual: float | None = Query(default=None),
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
    declination: int | None = Query(default=None),
    azimuth: int | None = Query(default=None),
    kwp: float | None = Query(default=None),
    inverter: float | None = Query(default=None),
) -> dict:
    """Return a Forecast.Solar-compatible forecast payload."""
    estimate_request = EstimateRequest(
        actual=actual,
        latitude=latitude,
        longitude=longitude,
        declination=declination,
        azimuth=(azimuth + 180 if azimuth is not None else None),
        kwp=kwp,
        inverter_kw=inverter,
        extra_planes=_parse_extra_planes(request),
    )
    result = await app.state.engine.build_estimate(estimate_request)
    tz = app.state.config.site.timezone
    summary = summarize_estimate_payload(result, timezone=tz)
    app.state.last_estimate_meta = {"unix_time": time.time(), **summary}
    return result


def _parse_extra_planes(request: Request) -> list[PlaneConfig]:
    """Parse `plane_<n>_*` query parameters passed by FC Lokal."""
    planes: list[PlaneConfig] = []
    index = 2

    while True:
        prefix = f"plane_{index}_"
        declination = request.query_params.get(f"{prefix}declination")
        azimuth = request.query_params.get(f"{prefix}azimuth")
        kwp = request.query_params.get(f"{prefix}kwp")
        if declination is None or azimuth is None or kwp is None:
            break

        planes.append(
            PlaneConfig(
                name=f"plane_{index}",
                declination=int(declination),
                azimuth=int(azimuth) + 180,
                kwp=float(kwp),
            )
        )
        index += 1

    return planes
