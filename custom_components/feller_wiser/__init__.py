"""Wiser by Feller µGateway integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NotAWiserGatewayError,
    UnauthorizedError,
    WiserApiError,
    WiserClient,
    WiserConnectionError,
    WiserWebSocket,
)
from .const import (
    CONF_TOKEN,
    DEFAULT_REGISTER_BUTTONS,
    DOMAIN,
    OPT_REGISTER_BUTTONS,
    PLATFORMS,
)
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry, WiserRuntimeData
from .naming import gateway_device_info
from .repairs import async_check_issues, async_create_serial_mismatch_issue
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register integration-wide services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WiserConfigEntry) -> bool:
    """Connect to the gateway, load the structure, start the websocket."""
    session = async_get_clientsession(hass)
    client = WiserClient(entry.data[CONF_HOST], session, token=entry.data[CONF_TOKEN])

    try:
        info = await client.get_info()
    except NotAWiserGatewayError as err:
        raise ConfigEntryError(f"{client.host} is not a Wiser µGateway: {err}") from err
    except WiserConnectionError as err:
        raise ConfigEntryNotReady(f"Cannot reach {client.host}: {err}") from err
    if entry.unique_id and info.sn != entry.unique_id:
        async_create_serial_mismatch_issue(hass, entry, info.sn)
        raise ConfigEntryError(
            f"Gateway at {client.host} has serial {info.sn}, expected {entry.unique_id}"
        )
    try:
        await client.get_account()
    except UnauthorizedError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except WiserApiError as err:
        raise ConfigEntryNotReady(f"Gateway rejected the token check: {err}") from err
    except WiserConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = WiserCoordinator(hass, entry, client)
    await coordinator.async_load_structure()
    await coordinator.async_config_entry_first_refresh()

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id, **gateway_device_info(coordinator.data, client.host)
    )

    websocket = WiserWebSocket(
        client.ws_url,
        entry.data[CONF_TOKEN],
        session,
        on_event=coordinator.handle_ws_event,
        on_connection=coordinator.handle_ws_connection,
        on_auth_failed=coordinator.handle_ws_auth_failed,
    )
    entry.runtime_data = WiserRuntimeData(
        client=client, coordinator=coordinator, websocket=websocket
    )
    coordinator.ws_stats = websocket.stats.as_dict

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await websocket.async_start()

    if entry.options.get(OPT_REGISTER_BUTTONS, DEFAULT_REGISTER_BUTTONS):
        await _async_register_buttons(coordinator)
    coordinator.async_start_device_details()
    async_check_issues(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_register_buttons(coordinator: WiserCoordinator) -> None:
    data = coordinator.data
    if not data.buttons_supported:
        return
    sleeping = [b for b in data.buttons.values() if not b.registered]
    if not sleeping:
        return
    _LOGGER.info("Registering %d sleeping buttons for events", len(sleeping))
    for button in sleeping:
        try:
            registered = await coordinator.client.register_button(button.device, button.channel)
        except (WiserConnectionError, WiserApiError) as err:
            _LOGGER.warning("Could not register button %s: %s", button.unique_key, err)
            continue
        data.buttons[registered.unique_key] = registered
    coordinator.async_update_listeners()


async def _async_update_listener(hass: HomeAssistant, entry: WiserConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: WiserConfigEntry) -> bool:
    """Stop the websocket and unload the platforms."""
    runtime = entry.runtime_data
    for controller in runtime.tilt_controllers.values():
        await controller.cancel()
        controller.close()
    await runtime.websocket.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await runtime.coordinator.async_shutdown()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: WiserConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices the gateway no longer knows."""
    data = entry.runtime_data.coordinator.data
    known = {data.info.sn, *data.devices.keys()}
    return not any(
        domain == DOMAIN and ident in known for domain, ident in device_entry.identifiers
    )
