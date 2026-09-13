"""Coordinator: websocket push first, REST poll as reconciliation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ApiLockedError,
    ButtonEvent,
    Device,
    FindMeEvent,
    FlagEvent,
    HvacEvent,
    LoadEvent,
    MotorOutputConfig,
    RequestFailedError,
    SensorEvent,
    UnauthorizedError,
    WiserApiError,
    WiserClient,
    WiserConnectionError,
    WsEvent,
)
from .const import (
    DEFAULT_POLL_INTERVAL,
    DEVICE_DETAIL_PAUSE_S,
    DOMAIN,
    EVENT_BUTTON,
    EVENT_FINDME,
    OPT_POLL_INTERVAL,
    OPT_READ_MOTOR_CONFIG,
    POLL_INTERVAL_WS_DOWN,
    SIGNAL_BUTTON_EVENT,
    SIGNAL_STRUCTURE_UPDATED,
    STORAGE_KEY_DETAILS,
    STORAGE_VERSION,
    STRUCTURE_REFRESH_INTERVAL_S,
)
from .data import WiserConfigEntry, WiserData

_LOGGER = logging.getLogger(__name__)


class WiserCoordinator(DataUpdateCoordinator[WiserData]):
    """Holds :class:`WiserData` and keeps it fresh."""

    config_entry: WiserConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WiserConfigEntry, client: WiserClient) -> None:
        """Create the coordinator (no I/O)."""
        self.client = client
        self._poll_interval = timedelta(
            seconds=entry.options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self._poll_interval,
            always_update=False,
        )
        self._structure_loaded_at = 0.0
        self._details_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_DETAILS.format(entry.entry_id)
        )
        self._details_task: asyncio.Task[None] | None = None
        self._load_listeners: dict[int, list[Callable[[], None]]] = {}
        self.ws_stats: Callable[[], dict[str, Any]] = dict

    # ------------------------------------------------------------------ structure
    async def async_load_structure(self) -> WiserData:
        """Fetch everything except live state; called at setup and periodically."""
        client = self.client
        try:
            info = await client.get_info()
            site = await client.get_site()
            data = self.data if self.data is not None else WiserData(info=info, site=site)
            data.info = info
            data.site = site
            try:
                data.net = await client.get_net_state()
            except WiserApiError as err:
                _LOGGER.debug("net/state not available: %s", err)
            data.loads = {load.id: load for load in await client.get_loads() if not load.unused}
            data.rooms = {room.id: room for room in await client.get_rooms()}
            devices = {device.id: device for device in await client.get_devices()}
            # keep details we already fetched
            for device_id, device in devices.items():
                old = data.devices.get(device_id)
                if old is not None and old.has_details and old.fw_version == device.fw_version:
                    devices[device_id] = device.with_details(old)
            data.devices = devices
            data.scenes = {scene.id: scene for scene in await client.get_scenes()}
            data.jobs = {job.id: job for job in await client.get_jobs()}
            data.sensors = {sensor.id: sensor for sensor in await client.get_sensors()}
            data.hvac_groups = {group.id: group for group in await client.get_hvac_groups()}
            data.flags = {flag.id: flag for flag in await client.get_flags()}
            try:
                data.buttons = {b.unique_key: b for b in await client.get_buttons()}
                data.buttons_supported = True
            except RequestFailedError as err:
                _LOGGER.info("Gateway has no button API (firmware too old?): %s", err)
                data.buttons = {}
                data.buttons_supported = False
        except UnauthorizedError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (WiserConnectionError, ApiLockedError, WiserApiError) as err:
            raise UpdateFailed(f"Cannot load gateway structure: {err}") from err
        data.structure_version += 1
        self._structure_loaded_at = time.monotonic()
        if self.data is None:
            self.data = data
        await self._async_apply_cached_details(data)
        self._async_sync_registries(data)
        async_dispatcher_send(
            self.hass, SIGNAL_STRUCTURE_UPDATED.format(self.config_entry.entry_id)
        )
        return data

    async def _async_apply_cached_details(self, data: WiserData) -> None:
        cached = await self._details_store.async_load() or {}
        for device_id, entry in cached.items():
            device = data.devices.get(device_id)
            if device is None or not isinstance(entry, dict):
                continue
            if entry.get("fw_version") != device.fw_version:
                continue
            detailed = Device.from_api({"id": device_id, **entry.get("detail", {})})
            data.devices[device_id] = device.with_details(detailed)
            for key, raw in (entry.get("motor_configs") or {}).items():
                data.motor_configs[key] = MotorOutputConfig.from_api(raw)
        data.details_complete = all(d.has_details for d in data.devices.values())

    # ------------------------------------------------------------------ polling
    async def _async_update_data(self) -> WiserData:
        """REST reconciliation; the websocket delivers most changes earlier."""
        if self.data is None:
            await self.async_load_structure()
        data = self.data
        client = self.client
        try:
            if time.monotonic() - self._structure_loaded_at > STRUCTURE_REFRESH_INTERVAL_S:
                await self.async_load_structure()
            states = await client.get_load_states()
            for load_id, state in states.items():
                if load_id in data.loads:
                    data.load_states[load_id] = state
            for sensor in await client.get_sensors():
                data.sensors[sensor.id] = sensor
            if data.hvac_groups:
                data.hvac_states.update(await client.get_hvac_states())
            for flag in await client.get_flags():
                data.flags[flag.id] = flag
            try:
                data.health = await client.get_health()
                data.rssi = await client.get_rssi()
            except WiserApiError as err:
                _LOGGER.debug("health/rssi not available: %s", err)
        except UnauthorizedError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (WiserConnectionError, ApiLockedError, WiserApiError) as err:
            raise UpdateFailed(f"Error communicating with the gateway: {err}") from err
        return data

    # ------------------------------------------------------------------ websocket
    @callback
    def handle_ws_event(self, event: WsEvent) -> None:
        """Merge a websocket event into the data and notify listeners."""
        data = self.data
        if data is None:
            return
        if isinstance(event, LoadEvent):
            if event.id not in data.loads:
                return
            current = data.load_states.get(event.id)
            data.load_states[event.id] = (
                current.merge(event.state) if current is not None else current_from(event.state)
            )
            self._notify_load(event.id)
        elif isinstance(event, SensorEvent):
            sensor = data.sensors.get(event.id)
            if sensor is None:
                return
            if "value" in event.data:
                data.sensors[event.id] = sensor.with_value(event.data["value"])
        elif isinstance(event, HvacEvent):
            current_hvac = data.hvac_states.get(event.id)
            data.hvac_states[event.id] = (
                current_hvac.merge(event.state)
                if current_hvac is not None
                else hvac_from(event.state)
            )
        elif isinstance(event, FlagEvent):
            flag = data.flags.get(event.id)
            if flag is not None and "value" in event.data:
                data.flags[event.id] = flag.with_value(bool(event.data["value"]))
        elif isinstance(event, ButtonEvent):
            self._fire_button_event(event)
            return
        elif isinstance(event, FindMeEvent):
            self.hass.bus.async_fire(
                EVENT_FINDME, {"config_entry_id": self.config_entry.entry_id, **event.target}
            )
            return
        else:
            _LOGGER.debug("Unhandled websocket event: %s", event.raw)
            return
        self.async_update_listeners()

    @callback
    def handle_ws_connection(self, connected: bool) -> None:
        """Adapt polling to the websocket state."""
        if self.data is not None:
            self.data.ws_connected = connected
        if connected:
            _LOGGER.debug("Websocket up, polling every %s", self._poll_interval)
            self.update_interval = self._poll_interval
        else:
            _LOGGER.debug("Websocket down, polling every %s s", POLL_INTERVAL_WS_DOWN)
            self.update_interval = timedelta(seconds=POLL_INTERVAL_WS_DOWN)
        self.hass.async_create_task(self.async_request_refresh())
        self.async_update_listeners()

    @callback
    def handle_ws_auth_failed(self) -> None:
        """Token rejected on the websocket handshake: start reauth."""
        self.config_entry.async_start_reauth(self.hass)

    def _fire_button_event(self, event: ButtonEvent) -> None:
        data = self.data
        button = next((b for b in data.buttons.values() if b.id == event.id), None)
        if button is None:
            _LOGGER.debug("Button event for unknown button %s", event.id)
            return
        dev_reg = dr.async_get(self.hass)
        ha_device = dev_reg.async_get_device_by_identifier(
            (DOMAIN, button.device), self.config_entry.entry_id
        )
        payload = {
            "config_entry_id": self.config_entry.entry_id,
            "device_id": ha_device.id if ha_device else None,
            "wiser_device": button.device,
            "channel": button.channel,
            "button_id": event.id,
            "type": event.event,
            "button_type": event.type or button.sub_type,
        }
        self.hass.bus.async_fire(EVENT_BUTTON, payload)
        async_dispatcher_send(
            self.hass,
            SIGNAL_BUTTON_EVENT.format(f"{self.config_entry.entry_id}_{event.id}"),
            payload,
        )

    # ------------------------------------------------------------------ per-load listeners
    @callback
    def async_add_load_listener(
        self, load_id: int, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Call ``listener`` whenever the state of one load changes (cheap fan-out)."""
        self._load_listeners.setdefault(load_id, []).append(listener)

        def _remove() -> None:
            listeners = self._load_listeners.get(load_id, [])
            if listener in listeners:
                listeners.remove(listener)

        return _remove

    def _notify_load(self, load_id: int) -> None:
        for listener in list(self._load_listeners.get(load_id, [])):
            listener()

    @callback
    def async_set_load_state(self, load_id: int, state: Any) -> None:
        """Store a freshly read state (used by the tilt controller)."""
        if self.data is None:
            return
        self.data.load_states[load_id] = state
        self._notify_load(load_id)
        self.async_update_listeners()

    # ------------------------------------------------------------------ device details
    def async_start_device_details(self) -> None:
        """Fetch inputs/outputs and motor config in the background."""
        if self._details_task is not None and not self._details_task.done():
            return
        self._details_task = self.config_entry.async_create_background_task(
            self.hass, self._async_load_device_details(), name=f"{DOMAIN}-device-details"
        )

    async def _async_load_device_details(self) -> None:
        data = self.data
        if data is None:
            return
        cached = await self._details_store.async_load() or {}
        read_motor_config = self.config_entry.options.get(OPT_READ_MOTOR_CONFIG, True)
        changed = False
        for device_id in list(data.devices):
            device = data.devices.get(device_id)
            if device is None:
                continue
            entry = cached.get(device_id)
            if (
                isinstance(entry, dict)
                and entry.get("fw_version") == device.fw_version
                and device.has_details
                and (not read_motor_config or entry.get("motor_configs") is not None)
            ):
                continue
            try:
                detailed = await self.client.get_device(device_id)
            except (WiserConnectionError, WiserApiError) as err:
                _LOGGER.debug("Device details for %s failed: %s", device_id, err)
                data.details_failed.add(device_id)
                continue
            data.devices[device_id] = device.with_details(detailed)
            motor_configs: dict[str, Any] = {}
            has_motor = any(o.type == "motor" for o in detailed.outputs or ())
            if has_motor and read_motor_config:
                await self._wait_until_device_idle(device_id)
                try:
                    config = await self.client.read_device_config(device_id)
                except (WiserConnectionError, WiserApiError) as err:
                    _LOGGER.warning("Could not read motor configuration of %s: %s", device_id, err)
                    data.details_failed.add(device_id)
                else:
                    for channel, output in enumerate(detailed.outputs or ()):
                        if output.type != "motor":
                            continue
                        motor = config.motor_output(channel)
                        if motor is None:
                            continue
                        key = f"{device_id}_{channel}"
                        data.motor_configs[key] = motor
                        motor_configs[key] = motor.raw
            data.details_failed.discard(device_id)
            cached[device_id] = {
                "fw_version": device.fw_version,
                "detail": {
                    "inputs": [{"type": i.type} for i in detailed.inputs or ()],
                    "outputs": [
                        {"load": o.load, "type": o.type, "sub_type": o.sub_type}
                        for o in detailed.outputs or ()
                    ],
                },
                "motor_configs": motor_configs if (has_motor and read_motor_config) else {},
            }
            changed = True
            self.async_update_listeners()
            await asyncio.sleep(DEVICE_DETAIL_PAUSE_S)
        if changed:
            await self._details_store.async_save(cached)
        data.details_complete = all(d.has_details for d in data.devices.values())
        self.async_update_listeners()

    async def _wait_until_device_idle(self, device_id: str, max_wait: float = 30.0) -> None:
        data = self.data
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            moving = any(
                data.load_states.get(load.id) is not None and data.load_states[load.id].is_moving
                for load in data.loads_of_device(device_id)
            )
            if not moving:
                return
            await asyncio.sleep(1.0)

    async def async_reload_motor_configs(self) -> None:
        """Forget cached details and fetch them again (button / service)."""
        await self._details_store.async_remove()
        if self.data is not None:
            self.data.motor_configs.clear()
            self.data.devices = {
                k: Device.from_api(
                    {
                        "id": k,
                        "last_seen": v.last_seen,
                        "a": v.a and v.a.__dict__,
                        "c": v.c and v.c.__dict__,
                    }
                )
                for k, v in self.data.devices.items()
            }
        self.async_start_device_details()

    # ------------------------------------------------------------------ registries
    @callback
    def _async_sync_registries(self, data: WiserData) -> None:
        """Remove devices and entities that disappeared from the gateway.

        Unique ids of device-bound entities start with the 8-character Wiser device id
        (``{device}_{channel}...``); gateway-level ids start with the serial number.
        """
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        valid_ids = {data.info.sn, *data.devices.keys()}
        for device in dr.async_entries_for_config_entry(dev_reg, entry_id):
            ours = [ident for domain, ident in device.identifiers if domain == DOMAIN]
            if ours and not any(ident in valid_ids for ident in ours):
                _LOGGER.info("Removing stale device %s", ours)
                dev_reg.async_update_device(device.id, remove_config_entry_id=entry_id)
        valid_loads = {load.unique_key for load in data.loads.values()}
        valid_sensors = {sensor.unique_key for sensor in data.sensors.values()}
        for entity in er.async_entries_for_config_entry(ent_reg, entry_id):
            unique = entity.unique_id
            owner = unique.split("_", 1)[0]
            if owner not in valid_ids:
                stale = True
            elif owner == data.info.sn:
                stale = False
            else:
                prefix = "_".join(unique.split("_", 2)[:2])  # device_channel
                stale = (
                    prefix not in valid_loads
                    and prefix not in valid_sensors
                    and "_button_" not in unique
                )
            if stale:
                _LOGGER.info("Removing stale entity %s (%s)", entity.entity_id, unique)
                ent_reg.async_remove(entity.entity_id)

    async def async_shutdown(self) -> None:
        """Cancel background work."""
        if self._details_task is not None:
            self._details_task.cancel()
        await super().async_shutdown()


def current_from(state: dict[str, Any]) -> Any:
    """Build a LoadState from a partial frame when nothing is cached yet."""
    from .api import LoadState

    return LoadState.from_api(state)


def hvac_from(state: dict[str, Any]) -> Any:
    """Build an HvacState from a partial frame when nothing is cached yet."""
    from .api import HvacState

    return HvacState.from_api(state)
