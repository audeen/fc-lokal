"""Optional Rich terminal dashboard (enable with FC_LOKAL_LIVE_CONSOLE=1)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from zoneinfo import ZoneInfo


def summarize_estimate_payload(result: dict[str, Any], *, timezone: str) -> dict[str, Any]:
    """Extract compact stats from a Forecast.Solar-compatible estimate dict."""
    tz = ZoneInfo(timezone)
    today = datetime.now(tz).date()

    whd = (result.get("result") or {}).get("watt_hours_day") or {}
    today_wh: float | None = None
    for key, val in whd.items():
        try:
            if datetime.fromisoformat(key).date() == today:
                today_wh = float(val)
                break
        except (TypeError, ValueError):
            continue

    watts = (result.get("result") or {}).get("watts") or {}
    peak_w: float | None = None
    if watts:
        peak_w = max(float(v) for v in watts.values())

    return {
        "today_kwh": (today_wh / 1000.0) if today_wh is not None else None,
        "peak_kw": (peak_w / 1000.0) if peak_w is not None else None,
        "hour_slots": len(watts),
    }


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"


def _render_panel(app: FastAPI, *, tick: int, health_interval: int) -> Panel:
    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Key", style="cyan", width=18)
    table.add_column("Value", style="white")

    cfg = app.state.config
    table.add_row("Timezone", cfg.site.timezone)
    table.add_row("Planes", str(len(cfg.site.planes)))
    table.add_row("HA live", "yes" if cfg.home_assistant.enabled else "no")
    table.add_row("PVGIS", "yes" if cfg.pvgis.enabled else "no")

    meta = getattr(app.state, "last_estimate_meta", None)
    if meta:
        age = time.time() - meta["unix_time"]
        table.add_row("Last /estimate", _format_age(age) + " ago")
        if meta.get("today_kwh") is not None:
            table.add_row("Forecast today", f"{meta['today_kwh']:.2f} kWh")
        if meta.get("peak_kw") is not None:
            table.add_row("Peak (model)", f"{meta['peak_kw']:.2f} kW")
        table.add_row("Hourly points", str(meta.get("hour_slots", "—")))
    else:
        table.add_row("Last /estimate", "[dim]no request yet[/dim]")

    snap = getattr(app.state, "live_health_snapshot", None)
    if isinstance(snap, dict):
        if snap.get("error"):
            table.add_row("Health", f"[red]{snap['error']}[/red]")
        else:
            li = snap.get("live_inputs")
            if isinstance(li, dict) and "error" not in li:
                p = li.get("effective_live_pv_power_watts")
                if p is not None:
                    table.add_row("HA PV now", f"{float(p):.0f} W")
            pc = snap.get("pvgis_calibration")
            if isinstance(pc, dict) and pc.get("enabled"):
                fac = pc.get("factor")
                if fac is not None:
                    table.add_row("PVGIS factor", f"{float(fac):.3f}")

    footer = (
        f"[dim]FC_LOKAL_LIVE_INTERVAL={tick}s"
        + (f"  HEALTH={health_interval}s" if health_interval else "")
        + "[/dim]"
    )

    return Panel(
        Group(table),
        title="[bold green]FC Lokal API[/bold green]  [dim]live[/dim]",
        subtitle=footer,
        border_style="green",
    )


async def _health_refresh_loop(app: FastAPI, interval: int) -> None:
    """Refresh heavy health payload in the background."""
    await asyncio.sleep(2)
    while True:
        try:
            app.state.live_health_snapshot = await app.state.engine.build_health()
        except Exception as err:
            app.state.live_health_snapshot = {"error": str(err)}
        await asyncio.sleep(interval)


async def run_live_console(app: FastAPI) -> None:
    """Run until cancelled (server shutdown)."""
    tick = max(1, int(os.getenv("FC_LOKAL_LIVE_INTERVAL", "5")))
    health_interval = max(0, int(os.getenv("FC_LOKAL_LIVE_HEALTH_INTERVAL", "0")))

    if not sys.stdout.isatty():
        print(
            "fc-lokal-api: stdout is not a TTY — Rich live view may be blank; set tty: true on the service",
            file=sys.stderr,
            flush=True,
        )
    console = Console(force_terminal=True)
    app.state.live_health_snapshot = None

    health_task: asyncio.Task[None] | None = None
    if health_interval > 0:
        health_task = asyncio.create_task(_health_refresh_loop(app, health_interval))

    try:
        with Live(
            _render_panel(app, tick=tick, health_interval=health_interval),
            console=console,
            refresh_per_second=4,
        ) as live:
            while True:
                await asyncio.sleep(tick)
                live.update(_render_panel(app, tick=tick, health_interval=health_interval))
    finally:
        if health_task:
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
