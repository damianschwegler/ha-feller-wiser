# Manual test checklist (real µGateway)

Pre-flight: Home Assistant 2026.8+ on the Pi, gateway reachable
(`Test-NetConnection wiser-<sn>.local -Port 80`), any YAML-based control of the same loads
disabled or using different entity ids.

1. **Install**: HACS custom repository or `scripts/deploy_to_pi.ps1 -Restart`. Log shows
   `custom_components.feller_wiser` loaded.
2. **Discovery**: Settings → Devices & services shows the gateway (zeroconf or DHCP). Note
   whether the host is an IP or `.local` name.
3. **Claim**: start the flow, press a gateway button within 30 s, entry is created with the
   site name. Check which `source` was used (entry data) and that room names appear.
4. **Entities**: all blinds/lights present with Wiser names, rooms suggested as areas,
   diagnostic sensors on the gateway device, event entities for wall buttons.
5. **Blinds**: open / close / stop; `is_opening`/`is_closing` follow the websocket within a
   second; `set_cover_position 50` ends at level 5000; `set_cover_tilt_position 100` reaches
   step 9.
6. **Tilt clicks**: `feller_wiser.set_tilt_steps` 4 → 2 → 7 on one blind, watch the log for
   rounds; check `tilt_ms` attribute equals the device configuration.
7. **Wall switch**: press a wall button while a blind is idle; state updates without polling.
8. **Gateway reboot**: power-cycle; entities go unavailable then recover; push connection
   returns; `sockets` in `/api/system/health` back to baseline (no leaked websockets).
9. **Reauth**: delete the HA account on the gateway (or re-claim the same user elsewhere);
   the reauth flow appears; a new button press restores everything.
10. **Diagnostics**: download from the device page; token, MAC and serials redacted.
11. **Options**: change the polling interval; the entry reloads without errors.
12. **Unload/reload** from the UI: no lingering websocket (health `sockets` drops).

## API questions to verify

- Does `POST /api/account/claim` with a nonexistent `source` fail immediately (before the
  buttons flash)?
- Exact error message when no button is pressed within 30 s.
- Does a full downward travel reset `tilt` to 0?
- Does a `click` during a running tilt step stop it?
- Semantics of `last_seen`; which `flags` HVAC and dim states carry; websocket handshake
  behaviour with a bad token (401 vs. silent close).
