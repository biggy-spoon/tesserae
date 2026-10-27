# Companion Bluetooth status observations

Tesserae Companion can read a display's mode, battery percentage and firmware
version over an authenticated Bluetooth connection, then report those readings
to its paired Tesserae server. Settings shows the last confirmed mode and uses
newer phone readings in the existing battery and firmware fields, with their
Bluetooth source and collection time.

## Reporting a reading

Clients check the advertised `device_mode_observations` feature before reporting
mode. The additional `device_status_observations` feature enables the optional
battery and firmware readings. The paired Companion token needs
`device_setup:write`, and the display must already be registered.

Send `PUT /api/app/v1/devices/{device_id}/mode-observation` with a JSON body:

```json
{
  "mode": "bluetooth",
  "observed_at": "2026-01-02T03:04:05Z",
  "source": "ios_ble",
  "battery": {"percent": 65, "observed_at": "2026-01-02T03:04:06Z"},
  "firmware": {"version": "0.9.11", "observed_at": "2026-01-02T03:04:05Z"}
}
```

Success returns `204`. Mode is `bluetooth` or `wifi`; each timestamp is RFC 3339
with a timezone and cannot be more than five minutes in the future. Battery
percentage is an integer from 0 to 100. Firmware is a nonempty version string,
up to 128 characters, without control characters.

The server merges mode, battery and firmware by their own observation times.
Delayed retries cannot replace newer values, and omitting a reading preserves
the saved one. `GET /api/app/v1/devices` includes the saved `mode_observation`
for clients with `devices:read`.

## Meaning of the displayed status

These are saved observations. A newer Wi-Fi heartbeat reading takes precedence
over an older Bluetooth reading in Settings. Phone reports leave heartbeat
freshness, reachability, configured transport, quiet hours and push scheduling
unchanged. A successful report confirms that the server saved the observation;
it does not send a command to the display.
