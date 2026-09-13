"""Device registry information and naming rules."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .api import Device, Load
from .const import DOMAIN, MANUFACTURER
from .data import WiserData


def gateway_device_info(data: WiserData, host: str) -> DeviceInfo:
    """DeviceInfo of the µGateway itself."""
    info = data.info
    name = data.site.name or (data.net.hostname if data.net else "") or f"Wiser {info.sn}"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, info.sn)},
        manufacturer=MANUFACTURER,
        model="Wiser µGateway",
        model_id=info.product or None,
        name=name,
        sw_version=info.sw or None,
        hw_version=info.hw or None,
        serial_number=info.sn,
        configuration_url=f"http://{host}",
    )
    if data.net and data.net.mac_addr:
        device_info["connections"] = {(CONNECTION_NETWORK_MAC, data.net.mac_addr.lower())}
    return device_info


def device_name(data: WiserData, device: Device) -> str:
    """Room name if every load of the device is in one room, else model + short id."""
    loads = data.loads_of_device(device.id)
    rooms = {load.room for load in loads if load.room is not None}
    if len(rooms) == 1:
        room = data.room_name(next(iter(rooms)))
        if room:
            return room
    if len(loads) == 1 and loads[0].name and not loads[0].name.startswith(device.id):
        return loads[0].name
    return f"{device.model} {device.id[-4:]}"


def gateway_registry_id(hass: HomeAssistant, data: WiserData) -> str | None:
    """HA device-registry id of the gateway (for ``via_device_id``)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id != data.info.sn:
            continue
        gateway = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, data.info.sn), entry.entry_id
        )
        return gateway.id if gateway else None
    return None


def wiser_device_info(
    data: WiserData, device: Device, *, rooms_as_areas: bool, via_device_id: str | None = None
) -> DeviceInfo:
    """DeviceInfo of a physical Wiser device (actuator + control front)."""
    loads = data.loads_of_device(device.id)
    rooms = {load.room for load in loads if load.room is not None}
    suggested_area = data.room_name(next(iter(rooms))) if len(rooms) == 1 else None
    a, c = device.a, device.c
    sw = a.fw_version if a and a.fw_version else None
    if c and c.fw_version and c.fw_version != sw:
        sw = f"{sw} / {c.fw_version}" if sw else c.fw_version
    info = DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        manufacturer=MANUFACTURER,
        model=device.model,
        model_id=(a.comm_ref if a and a.comm_ref else None),
        name=device_name(data, device),
        sw_version=sw,
        hw_version=(a.hw_id if a and a.hw_id else None),
        serial_number=(a.serial_nr if a and a.serial_nr else None),
    )
    if via_device_id:
        info["via_device_id"] = via_device_id
    if rooms_as_areas and suggested_area:
        info["suggested_area"] = suggested_area
    return info


def load_entity_name(data: WiserData, load: Load, device: Device | None) -> str | None:
    """Entity name; ``None`` lets the entity take the device name (avoids 'Büro Büro').

    A leading device/room name is stripped ("Schlafzimmer Seite" in room "Schlafzimmer"
    becomes "Seite"), so the resulting entity id reads ``cover.schlafzimmer_seite``.
    """
    name = load.name.strip()
    if not name or name.startswith(load.device):
        return None
    if device is None:
        return name
    dev_name = device_name(data, device).strip()
    if name.casefold() == dev_name.casefold():
        return None
    if dev_name and name.casefold().startswith(dev_name.casefold() + " "):
        return name[len(dev_name) :].strip() or None
    return name
