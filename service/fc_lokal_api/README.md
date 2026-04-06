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
3. Adjust coordinates and panel data
4. Start the service:

```bash
docker compose up -d --build
```

5. Test locally:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/estimate
```

## Notes on your sensors

The provided example config uses these candidate entities from your HA instance:

- `sensor.solakon_one_active_power`
- `sensor.solakon_one_daily_generation`
- `sensor.shellypro3em_ac15187c6ea4_total_active_power`
- `sensor.solakon_one_battery_combined_power`

If `sensor.solakon_one_total_pv_power` turns out to be the more precise live PV sensor, replace
`pv_power_entity_id` with that entity in `data/config.yaml`.
