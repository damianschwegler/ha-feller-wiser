"""Diagnostics download."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_TOKEN, DOMAIN
from .data import WiserConfigEntry

TO_REDACT = {CONF_TOKEN, "secret", "mac_addr", "ip", "serial_nr", "instance_id", "login", "company"}


def _dump(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _dump(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_dump(v) for v in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WiserConfigEntry
) -> dict[str, Any]:
    """Everything the coordinator knows, with secrets removed."""
    runtime = entry.runtime_data
    data = runtime.coordinator.data
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "info": _dump(data.info),
            "site": _dump(data.site),
            "net": _dump(data.net),
            "health": _dump(data.health),
            "rssi": data.rssi,
            "websocket": {"connected": data.ws_connected, **runtime.websocket.stats.as_dict()},
            "counts": {
                "loads": len(data.loads),
                "devices": len(data.devices),
                "rooms": len(data.rooms),
                "scenes": len(data.scenes),
                "sensors": len(data.sensors),
                "buttons": len(data.buttons),
                "hvac_groups": len(data.hvac_groups),
                "flags": len(data.flags),
            },
            "details_complete": data.details_complete,
            "details_failed": sorted(data.details_failed),
            "loads": _dump(data.loads),
            "load_states": _dump(data.load_states),
            "motor_configs": _dump(data.motor_configs),
            "devices": _dump(data.devices),
            "rooms": _dump(data.rooms),
            "scenes": _dump(data.scenes),
            "jobs": _dump(data.jobs),
            "sensors": _dump(data.sensors),
            "buttons": _dump(data.buttons),
            "hvac_groups": _dump(data.hvac_groups),
            "hvac_states": _dump(data.hvac_states),
            "flags": _dump(data.flags),
            "tilt": {
                str(load_id): (c.last_outcome.as_dict() if c.last_outcome else None)
                for load_id, c in runtime.tilt_controllers.items()
            },
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: WiserConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Subset for one device."""
    data = entry.runtime_data.coordinator.data
    wiser_ids = [ident for domain, ident in device.identifiers if domain == DOMAIN]
    loads = {lid: load for lid, load in data.loads.items() if load.device in wiser_ids}
    return async_redact_data(
        {
            "identifiers": wiser_ids,
            "device": _dump([data.devices[i] for i in wiser_ids if i in data.devices]),
            "loads": _dump(loads),
            "load_states": _dump({lid: data.load_states.get(lid) for lid in loads}),
            "motor_configs": _dump(
                {k: v for k, v in data.motor_configs.items() if k.split("_")[0] in wiser_ids}
            ),
            "buttons": _dump({k: b for k, b in data.buttons.items() if b.device in wiser_ids}),
            "sensors": _dump({sid: s for sid, s in data.sensors.items() if s.device in wiser_ids}),
        },
        TO_REDACT,
    )
