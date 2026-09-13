# Wiser by Feller µGateway API – working notes

Sources: [Feller-AG/wiser-api](https://github.com/Feller-AG/wiser-api) (OpenAPI 6.0.43,
changelog up to 6.0.46) and [Feller-AG/wiser-tutorial](https://github.com/Feller-AG/wiser-tutorial).
Everything below is what this integration relies on.

## Transport

- Base URL `http://<host>/api`, HTTP/1.1, JSON both ways.
- Every response is a JSend envelope, **always with HTTP 200**:
  `{"status": "success", "data": ...}` or `{"status": "error", "message": "..."}`.
- Known error messages: `api is locked, ...` (no/invalid token), `unauthorized user`
  (token unknown), `... is not a directory` (claim `source` account missing),
  `no site info` (site not finished in the app).
- The gateway is a small MicroPython device (~80 KB free heap). Send one request at a time.
- Token-free: `GET /api/info`, `GET /api/info/debug`, `GET /api/site`, `POST /api/account/claim`.

## Onboarding

`POST /api/account/claim {"user": "<name>", "source": "<existing account>"}` blocks up to
30 s while the gateway buttons flash purple; one physical button press returns
`{"user": ..., "secret": "<uuid4>"}`. The secret is the bearer token (`Authorization: Bearer <secret>`)
and never expires. Re-claiming the same `user` replaces the old secret. `source` copies the
per-account data (rooms, load names/rooms/kinds, scenes, group controls) from that account:
`admin` = Wiser Home app, `installer` = Wiser installer/e-Setup app. `POST /api/account/clone`
creates another token without a button press; `DELETE /api/account` revokes.

## Discovery

mDNS `_http._tcp.local.` with instance name `wiser-<sn>`, DHCP hostname `wiser-<sn>`.
`GET /api/info` → `sn`, `api` (`"2.0"` for µGateway v2), `sw`, `hw`, `product`.
`GET /api/net/state` → `hostname`, `ip`, `mac_addr`. `GET /api/net/rssi` → dBm (station mode only).

## Loads

`GET /api/loads` → `id`, `name`, `type` (`onoff`, `dim`, `motor`, `dali`), `sub_type`
(`""`, `dto`, `tw`, `rgb`, `relay`), `device`, `channel`, `unused`, app-only `room`, `kind`.
`kind`: lights Light 0 / Switch 1; motors Motor 0 / Venetian blinds 1 / Roller shutters 2 / Awnings 3.

State (`GET /api/loads/state`, `GET /api/loads/{id}/state`, websocket `load` frames):

| type | state fields |
|---|---|
| onoff, dim, dali | `bri` 0–10000 (+ `ct` 1000–20000 K for `tw`, `red/green/blue/white` 0–255 for `rgb`), `flags` |
| motor | `level` 0 = open … 10000 = closed, `tilt` 0–9 (step counter, **not an angle**), `moving` `up`/`down`/`stop`, `flags` `{direction, learning, moving, under_current, over_current, timeout, locked}` |

Commands:

- `PUT /api/loads/{id}/target_state` with the fields above. A motor `tilt` always triggers a
  reference run (down to 0, then up to the target).
- `PUT /api/loads/{id}/ctrl {"button": on|off|up|down|toggle|stop, "event": click|press|release}`.
  Motor: `click` on up/down while stopped = exactly one tilt step, `click` while moving = stop,
  `press` = full travel. Single clicks can get lost (observed in the field), so verify.
- `PUT /api/loads/{id}/ping` flashes the button LED.

## Devices

`GET /api/devices` (fast) → `id` (8 hex chars), `last_seen`, `a` (actuator block) and `c`
(control front) with `fw_version`, `comm_ref`, `comm_name` (German), `serial_nr`.
`GET /api/devices/{id}` adds `inputs[{type}]` and `outputs[{load, type, sub_type}]` but takes
~1 s per device on the first call. `GET /api/devices/{id}/config` creates a configuration
object and puts the device in config mode; `DELETE /api/devices/config/{cfg}` discards it.
Motor outputs carry `tilt_ms` (duration of one tilt step) and `tiltable`.

## Other collections

Rooms `{id, name, kind, load_order}` (per account), scenes `{id, name, kind, job}` executed
via `GET /api/jobs/{job}/run`, sensors `{id, name, type, unit, value, device, channel}`
(types temperature, illuminance/brightness, wind, rain, hail, humidity, CO2, window),
buttons `{id|null, device, channel, type, sub_type, job}` – `id: null` means the button is
"sleeping" and sends no events until `POST /api/buttons {device, channel}`, HVAC groups
(`GET /api/hvacgroups/state`, `PUT /api/hvacgroups/{id}/target_state {target_temperature}`),
system flags `{id, symbol, value, name}` (`PATCH` to set), `GET /api/system/health`.

## Websocket

`ws://<host>/api` with the same `Authorization` header on the handshake. One JSON object per
text frame, **only changes**: `{"load": {"id": 3, "state": {...partial...}}}`,
`{"sensor": {"id": 19, "value": 20.1}}`, `{"hvacgroup": ...}`, `{"flag": {...}}`,
`{"button": {"id": 101, "cmd": {"event": "click", "type": "..."}}}`, `{"findme": {...}}`.
Commands: `{"command": "dump_loads"}` (one `load` frame per load) and
`{"command": "ctrl_loads", "id": 1, "button": "on", "event": "click"}` (errors are dropped
silently – this integration only controls via REST). No application-level keepalive.

## Open questions verified on real hardware

See `docs/manual-test-checklist.md`, section "API questions".
