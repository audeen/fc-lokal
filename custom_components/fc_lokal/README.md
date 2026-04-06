# FC Lokal

`FC Lokal` is a minimal fork of Home Assistant's built-in `forecast_solar` integration.
It keeps the existing `Estimate`-based sensor and Energy Dashboard logic, but adds an optional
local/custom HTTP source and uses its own domain `fc_lokal`, so it can run in parallel with the
core `forecast_solar` integration.

## Installation

1. Install this repository with HACS as a custom integration repository, or copy `fc_lokal` into `/config/custom_components/`.
2. Restart Home Assistant.
3. Add the `FC Lokal` integration in the UI.
4. In the options flow, choose the desired `source_mode`.

## New options

- `source_mode`: `forecast_solar_api` or `custom_api`
- `base_url`: base URL of the local/custom endpoint, used only for `custom_api`
- `use_live_actual`: when enabled, forwards a Home Assistant sensor value as `actual`
- `actual_sensor_entity_id`: entity used for the `actual` query parameter
- `request_timeout`: timeout in seconds for custom API requests

## Local endpoint

The integration calls:

- `GET {base_url}/estimate`

Expected response format:

```json
{
  "result": {
    "watts": {
      "2026-04-06T12:00:00+02:00": 1234
    },
    "watt_hours_period": {
      "2026-04-06T12:00:00+02:00": 456
    },
    "watt_hours_day": {
      "2026-04-06T00:00:00+02:00": 7890
    }
  },
  "message": {
    "ratelimit": {
      "limit": 9999
    },
    "info": {
      "timezone": "Europe/Berlin"
    }
  }
}
```

Optional query parameter when enabled:

- `actual=<float>`

Additional informational query parameters such as `latitude`, `longitude`, `declination`,
`azimuth`, `kwp`, damping values, inverter size, and extra plane values are also forwarded.
Custom endpoints may ignore them.

## Known limitations

- The integration still depends on the Python package `forecast-solar==5.0.0` for `Estimate`
  parsing and compatibility with the existing sensor and energy code.
- `FC Lokal` can still use the upstream Forecast.Solar API if `source_mode=forecast_solar_api`.
