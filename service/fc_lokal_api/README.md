# FC Lokal API Service

This is the Proxmox-side service for the `FC Lokal` Home Assistant integration.
It exposes `GET /estimate` and returns Forecast.Solar-compatible JSON.

## Data sources

- PVGIS: free official JRC API for PV baseline data
- Open-Meteo: free no-key weather and irradiance forecast API
- Home Assistant REST API: live correction using entity states

## Endpoints

- `GET /health`
- `GET /estimate`

`/estimate` accepts the same main query parameters that the `FC Lokal` HA integration forwards:

- `actual`
- `latitude`
- `longitude`
- `declination`
- `azimuth`
- `kwp`
- `inverter`
- `plane_2_*`, `plane_3_*`, ...

## Quick start

1. Copy `config.example.yaml` to `data/config.yaml`
2. Fill in your Home Assistant URL and long-lived token
3. Adjust coordinates, panel data, and hardware limits
4. Start the service:

```bash
docker compose up -d --build
```

5. Test locally:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/estimate
```

If you change `data/config.yaml`, restart the service so the new config is loaded:

```bash
docker compose up -d --build
```

If `/estimate` returns an error, inspect the container logs:

```bash
docker compose logs --tail=100 fc-lokal-api
```

## Notes on your sensors

The provided example config is tuned for your Solakon + Shelly setup and uses these
candidate entities from your HA instance:

- `sensor.solakon_one_total_pv_power`
- `sensor.solakon_one_daily_generation`
- `sensor.solakon_one_active_power`
- `sensor.shellypro3em_ac15187c6ea4_total_active_power`
- `sensor.solakon_one_battery_combined_power`

`pv_power_entity_id` should point to the best available total PV power sensor. If that sensor is
missing or unavailable, the service falls back to:

- inverter AC output power
- plus battery charge power
- optionally reduced by grid import if battery charging from grid is possible

## Limits and interpretation

The example config separates three different hardware limits:

- `grid_output_limit_watts`: maximum AC power delivered to the house/grid
- `battery_charge_limit_watts`: maximum battery charge power
- `system_total_limit_watts`: maximum total PV production that should clip the forecast

For your described setup, a good starting point is:

```yaml
site:
  grid_output_limit_watts: 1200
  battery_charge_limit_watts: 2600
  system_total_limit_watts: 2600
```

The Home Assistant sensor interpretation is also configurable:

```yaml
home_assistant:
  interpretation:
    battery_power_sign: negative_is_charging
    grid_power_sign: positive_is_import
    battery_charging_from_grid_possible: false
```

This means:

- negative battery power values are treated as charging
- positive grid power values are treated as import
- battery charge power is assumed to come from PV, not from the grid
