"""Switch platform: onoff loads flagged as switch, and system flags."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    BRI_MAX,
    CtrlButton,
    CtrlEvent,
    LightKind,
    LoadType,
    WiserApiError,
    WiserConnectionError,
)
from .const import ATTR_LOAD_ID, DOMAIN, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserGatewayEntity, WiserLoadEntity
from .services import async_register_load_entity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create switch entities."""
    coordinator = entry.runtime_data.coordinator
    known_loads: set[int] = set()
    known_flags: set[int] = set()

    @callback
    def _add_new() -> None:
        new: list[SwitchEntity] = []
        for load in coordinator.data.loads.values():
            if load.id in known_loads:
                continue
            if load.type is LoadType.ONOFF and load.kind == LightKind.SWITCH:
                known_loads.add(load.id)
                new.append(WiserLoadSwitch(coordinator, load))
        for flag in coordinator.data.flags.values():
            if flag.id in known_flags:
                continue
            known_flags.add(flag.id)
            new.append(WiserFlagSwitch(coordinator, flag.id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserLoadSwitch(WiserLoadEntity, SwitchEntity):
    """onoff load used as switch/outlet."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    async def async_added_to_hass(self) -> None:
        """Register for the raw ctrl service."""
        await super().async_added_to_hass()
        self.async_on_remove(async_register_load_entity(self.hass, self))

    @property
    def is_on(self) -> bool | None:
        """Bri > 0."""
        state = self.state_data
        return None if state is None or state.bri is None else state.bri > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw values."""
        return {ATTR_LOAD_ID: self.load_id}

    async def _target(self, bri: int) -> None:
        try:
            await self.coordinator.client.set_target_state(self.load_id, bri=bri)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        """On."""
        await self._target(BRI_MAX)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Off."""
        await self._target(0)

    async def async_load_ctrl(self, button: str, event: str) -> None:
        """Raw ctrl (service)."""
        try:
            await self.coordinator.client.ctrl(self.load_id, CtrlButton(button), CtrlEvent(event))
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err


class WiserFlagSwitch(WiserGatewayEntity, SwitchEntity):
    """A user defined system flag of the gateway (used by Wiser jobs/conditions)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:flag-variant"

    def __init__(self, coordinator: WiserCoordinator, flag_id: int) -> None:
        """Unique id ``{sn}_flag_{id}``."""
        super().__init__(coordinator, f"flag_{flag_id}")
        self._flag_id = flag_id

    @property
    def name(self) -> str:
        """Flag name or symbol."""
        flag = self.data.flags.get(self._flag_id)
        if flag is None:
            return f"Flag {self._flag_id}"
        return flag.name or flag.symbol

    @property
    def available(self) -> bool:
        """Only while the flag exists."""
        return super().available and self._flag_id in self.data.flags

    @property
    def is_on(self) -> bool | None:
        """Flag value."""
        flag = self.data.flags.get(self._flag_id)
        return None if flag is None else flag.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Symbol for Wiser conditions."""
        flag = self.data.flags.get(self._flag_id)
        return {"symbol": flag.symbol if flag else None, "flag_id": self._flag_id}

    async def _set(self, value: bool) -> None:
        try:
            flag = await self.coordinator.client.set_flag(self._flag_id, value)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self.data.flags[self._flag_id] = flag
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear."""
        await self._set(False)
