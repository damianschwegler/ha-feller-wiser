# Wiser by Feller for Home Assistant

[![CI](https://github.com/damianschwegler/ha-feller-wiser/actions/workflows/ci.yml/badge.svg)](https://github.com/damianschwegler/ha-feller-wiser/actions/workflows/ci.yml)
[![Validate](https://github.com/damianschwegler/ha-feller-wiser/actions/workflows/validate.yml/badge.svg)](https://github.com/damianschwegler/ha-feller-wiser/actions/workflows/validate.yml)

Local, push-based Home Assistant integration for the **Wiser by Feller µGateway**
(Feller AG, Switzerland). It talks to the gateway's REST and websocket API directly, needs no
cloud, and is set up by pressing one button on the gateway.

*[Deutsche Kurzanleitung weiter unten.](#kurzanleitung-deutsch)*

## Highlights

- **One-button setup** – the gateway is discovered via mDNS/DHCP; you confirm, press any
  button on the µGateway, done. Rooms, names and scenes are copied from the Wiser app.
- **Push updates** over the gateway websocket; REST polling only as a safety net.
- **Blinds done right** – slat tilt uses single tilt-step commands relative to the current
  position (no visible reference run), verifies the result and corrects lost steps. The step
  duration is read from the device configuration. A raw `tilt_step` number entity and the
  services `set_tilt_steps`, `set_target_state` and `load_ctrl` expose the Wiser scale directly.
- **Everything the gateway offers**: lights (on/off, dim, DALI tunable white and RGBW),
  switches, blinds/shutters/awnings, scenes, sensors (weather station, thermostat),
  heating groups, system flags, wall buttons as event entities and device triggers,
  gateway diagnostics, repairs and downloadable diagnostics.
- Gentle on the gateway: one request at a time, slow endpoints fetched lazily in the
  background and cached.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → *Custom repositories* → add
   `https://github.com/damianschwegler/ha-feller-wiser` as *Integration*.
2. Download **Wiser by Feller**, restart Home Assistant.
3. Settings → Devices & services: the µGateway is discovered automatically. Otherwise add
   the integration manually and enter `wiser-<serial>.local` or the IP address.
4. Press any button on the µGateway within 30 seconds when asked (its LEDs flash purple).

### Manual

Copy `custom_components/feller_wiser` into `<config>/custom_components/` and restart.

### Removal

Delete the integration entry in Settings → Devices & services. The account created on the
gateway (`homeassistant` by default) stays until you claim the name again or delete it via
the Wiser API; it does no harm.

## Entities

| Wiser object | Home Assistant |
|---|---|
| motor load (venetian blind) | `cover` with position and tilt, `number` tilt step (0–9), `binary_sensor` motor problem, `button` identify |
| motor load (shutter / awning / relay) | `cover` with position or open/close/stop only |
| onoff load | `light` (or `switch` when the app marks it as switch) |
| dim / DALI load | `light` with brightness, colour temperature or RGBW |
| scene | `scene` |
| sensor input | `sensor` (temperature, illuminance, wind, humidity, CO₂) or `binary_sensor` (rain, hail, window) |
| HVAC group | `climate` |
| system flag | `switch` |
| registered wall button | `event` (click / press / release) plus device triggers |
| gateway | `binary_sensor` push connection, diagnostic `sensor`s, `button`s to reload |

Entity ids are derived from the load names in the Wiser app (`cover.buro`,
`light.stehlampe`). Rename them freely in Home Assistant; renames survive updates.

## Services

| Service | Purpose |
|---|---|
| `feller_wiser.set_tilt_steps` | Tilt to a slat step 0–9 (`mode`: `auto`, `absolute`, `relative`, `reference`). Returns the outcome when called with `return_response`. |
| `feller_wiser.set_target_state` | Raw `level` (0 = open … 10000 = closed) and/or `tilt` (0–9) in one command. |
| `feller_wiser.load_ctrl` | Raw button/event (`up`/`down`/`stop`/`toggle`/`on`/`off` × `click`/`press`/`release`). |
| `feller_wiser.refresh_structure` | Re-read loads, rooms, devices, scenes and buttons. |

### How tilt works

The Wiser actuator does not know the slat angle. `tilt` is a counter 0–9 of tilt steps.
`target_state` with a tilt always drives to 0 first (reference run) and then up – slow and
visible. This integration instead sends single `click` commands relative to the current step
(pause = step duration from the device configuration + margin), reads the result back and
corrects up to three times. Step 0 or an unknown state still uses a reference run. Blinds
that are moving, locked by the weather protection or not calibrated are skipped and the
service reports `skipped_moving`, `skipped_locked`, `skipped_learning`.

Example automation action (close and set slats in one go, Wiser scale):

```yaml
action: feller_wiser.set_target_state
target:
  entity_id: cover.buro
data:
  level: 10000
  tilt: 4
```

## Options

Polling interval, automatic registration of wall buttons, rooms as areas, tilt mode and
timing (click margin, fallback pause, settle time, correction rounds, reference fallback),
reading of the motor configuration.

## Known limitations

- The gateway API has no way to switch a heating group off; `climate` only sets the target
  temperature.
- Dimmer transitions are not supported by the API.
- Rooms, names and scenes are copied from an existing Wiser account at setup time (`admin`
  from the Wiser Home app, otherwise `installer`). Use the *Reload structure* button after
  renaming things in the app.

## Development

```bash
scripts/setup.sh                 # uv sync (Python 3.14)
scripts/run_sim.sh               # fake µGateway on http://localhost:8080
scripts/develop.sh               # Home Assistant on http://localhost:8123
uv run pytest                    # unit + integration tests against the simulator
uv run ruff check . && uv run mypy
```

The repository ships a **dev container** (VS Code → *Reopen in Container*) with everything
pre-installed. On Windows, run `uv run python scripts/install_windows_shims.py` once to stub
the POSIX modules Home Assistant imports; the dev container and CI do not need this.

`simulator/` is a complete fake µGateway (REST + websocket, motor physics, fault injection)
used by the tests and for manual UI testing. `docs/api-notes.md` summarises the gateway API.

## Kurzanleitung (Deutsch)

1. In HACS das Repository `https://github.com/damianschwegler/ha-feller-wiser` als
   *Integration* hinzufügen, «Wiser by Feller» herunterladen, Home Assistant neu starten.
2. Einstellungen → Geräte & Dienste: das µGateway wird automatisch gefunden (sonst
   `wiser-<Seriennummer>.local` eingeben).
3. Innerhalb von 30 Sekunden eine beliebige Taste am µGateway drücken. Räume und Namen
   werden aus der Wiser-App übernommen.

Storen: Position 100 % = offen. Der Tilt wird in einzelnen Kippschritten relativ gefahren
(ohne Referenzfahrt); die Aktion `feller_wiser.set_tilt_steps` nimmt Wiser-Schritte 0–9,
`cover.set_cover_tilt_position` nimmt Prozent (100 % = Lamellen horizontal).

## License

Apache-2.0. Not affiliated with Feller AG or Schneider Electric. See `NOTICE`.
