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
from rich.text import Text
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


def _w_to_kw_str(w: float | None) -> str | None:
    if w is None:
        return None
    return f"{w / 1000.0:.2f} kW"


def _render_panel(app: FastAPI, *, tick: int, health_interval: int) -> Panel:
    cfg = app.state.config
    tz = ZoneInfo(cfg.site.timezone)
    now = datetime.now(tz)
    clock = now.strftime("%Y-%m-%d %H:%M:%S")

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold bright_cyan",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Metric", style="cyan", min_width=22, no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row(
        "[bold]Local time[/bold]",
        Text.assemble(
            (clock, "bold green"),
            ("  ", ""),
            (cfg.site.timezone, "dim"),
        ),
    )
    table.add_section()

    table.add_row("Planes (PV surfaces)", str(len(cfg.site.planes)))
    table.add_row("Open-Meteo model", cfg.open_meteo.model)
    table.add_row("HA REST configured", "[green]yes[/green]" if cfg.home_assistant.enabled else "[dim]no[/dim]")
    table.add_row("PVGIS baseline", "[green]yes[/green]" if cfg.pvgis.enabled else "[dim]no[/dim]")

    lim = cfg.site
    cap = lim.effective_total_limit_watts()
    if cap is not None:
        table.add_row("System cap (clip)", _w_to_kw_str(cap) or "—")
    table.add_section()

    meta = getattr(app.state, "last_estimate_meta", None)
    if meta:
        age = time.time() - meta["unix_time"]
        table.add_row("[bold]Last /estimate[/bold]", "[dim]" + _format_age(age) + " ago[/dim]")
        if meta.get("today_kwh") is not None:
            table.add_row(
                "Forecast today (model)",
                f"[bold green]{meta['today_kwh']:.2f} kWh[/bold green]",
            )
        if meta.get("peak_kw") is not None:
            table.add_row("Peak power (model curve)", f"[yellow]{meta['peak_kw']:.2f} kW[/yellow]")
        slots = meta.get("hour_slots")
        table.add_row(
            "Hourly power slots",
            f"{slots}  [dim](forecast horizon × resolution)[/dim]",
        )
    else:
        table.add_row("[bold]Last /estimate[/bold]", "[dim]no request yet — curl /estimate[/dim]")
    table.add_section()

    snap = getattr(app.state, "live_health_snapshot", None)
    if isinstance(snap, dict):
        if snap.get("error"):
            table.add_row("[bold]Health snapshot[/bold]", f"[red]{snap['error']}[/red]")
        else:
            table.add_row("[bold]Health snapshot[/bold]", "[dim]from periodic /health[/dim]")
            li = snap.get("live_inputs")
            if isinstance(li, dict) and "error" not in li:
                src = li.get("effective_live_pv_source")
                p = li.get("effective_live_pv_power_watts")
                if p is not None:
                    row_val = f"{float(p):.0f} W"
                    if src:
                        row_val += f"  [dim]({src})[/dim]"
                    table.add_row("HA — effective PV now", row_val)
                bat = li.get("battery_charge_watts")
                if bat is not None:
                    table.add_row("HA — battery charge", f"{float(bat):.0f} W")
                gi = li.get("grid_import_watts")
                ge = li.get("grid_export_watts")
                if gi is not None or ge is not None:
                    table.add_row(
                        "HA — grid in / out",
                        f"{float(gi or 0):.0f} / {float(ge or 0):.0f} W",
                    )

            pc = snap.get("pvgis_calibration")
            if isinstance(pc, dict) and pc.get("enabled"):
                active = pc.get("active")
                fac = pc.get("factor")
                exp = pc.get("expected_energy_today_wh")
                mod = pc.get("modeled_energy_today_wh")
                raw = pc.get("raw_scale")
                if fac is not None:
                    fac_s = f"{float(fac):.3f}"
                    if active:
                        fac_s = f"[yellow]{fac_s}[/yellow]  [dim]active[/dim]"
                    table.add_row("PVGIS cal — blend factor", fac_s)
                if exp is not None and mod is not None:
                    table.add_row(
                        "PVGIS cal — E today (exp / model)",
                        f"{float(exp) / 1000:.2f} / {float(mod) / 1000:.2f} kWh",
                    )
                if raw is not None:
                    table.add_row("PVGIS cal — raw scale", f"{float(raw):.3f}")

    footer = (
        "[dim]refresh "
        + str(tick)
        + "s"
        + (f"  ·  health {health_interval}s" if health_interval else "")
        + "  ·  [italic]read-only dashboard[/italic][/dim]"
    )

    title = Text()
    title.append(" FC Lokal API ", style="bold white on green")
    title.append(" live ", style="dim")

    return Panel(
        Group(table),
        title=title,
        title_align="center",
        subtitle=footer,
        subtitle_align="left",
        border_style="bright_green",
        box=box.DOUBLE,
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
