# FC Lokal

FC Lokal is a HACS-ready custom integration for Home Assistant. It is based on the built-in
`forecast_solar` integration, but uses its own domain `fc_lokal` so it can be installed in
parallel to the core integration.

The fork keeps the existing Forecast.Solar sensor and Energy Dashboard behavior as intact as
possible and adds an optional custom HTTP source:

- `source_mode = forecast_solar_api` keeps the upstream behavior
- `source_mode = custom_api` calls your own endpoint at `GET {base_url}/estimate`
- optional `use_live_actual` forwards a Home Assistant entity state as `actual`

## Repository structure

This repository is prepared for HACS:

```text
custom_components/fc_lokal/
hacs.json
README.md
```

## Install with HACS

1. Push this repository to GitHub.
2. Update the placeholder GitHub URLs in `custom_components/fc_lokal/manifest.json`.
3. In HACS, open `Custom repositories`.
4. Add your GitHub repository URL as type `Integration`.
5. Install `FC Lokal` from HACS.
6. Restart Home Assistant.
7. Add the `FC Lokal` integration.

## Local endpoint contract

FC Lokal calls:

- `GET {base_url}/estimate`

Expected response:

```json
{
  "result": {
    "watts": {},
    "watt_hours_period": {},
    "watt_hours_day": {}
  },
  "message": {
    "ratelimit": {"limit": 9999},
    "info": {"timezone": "Europe/Berlin"}
  }
}
```

Optional forwarded query parameters:

- `actual`
- `latitude`
- `longitude`
- `declination`
- `azimuth`
- `kwp`
- `damping_morning`
- `damping_evening`
- `inverter`
- extra plane parameters

## Parallel operation

Because this fork uses `domain: fc_lokal`, it can coexist with the built-in `forecast_solar`
integration. That lets you keep the original integration installed while testing this fork.
