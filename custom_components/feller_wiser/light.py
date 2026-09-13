"""Light platform: onoff (kind light), dim and DALI loads."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGBW_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    BRI_MAX,
    CT_MAX,
    CT_MIN,
    CtrlButton,
    CtrlEvent,
    LightKind,
    Load,
    LoadSubType,
    LoadType,
    WiserApiError,
    WiserConnectionError,
)
from .const import ATTR_LOAD_ID, DOMAIN, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserLoadEntity
from .services import async_register_load_entity
from .util import bri_to_brightness, brightness_to_bri

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


def is_light(load: Load) -> bool:
    """Onoff loads are lights unless the app flagged them as switch."""
    if load.type in (LoadType.DIM, LoadType.DALI):
        return True
    return load.type is LoadType.ONOFF and load.kind != LightKind.SWITCH


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create light entities."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = []
        for load in coordinator.data.loads.values():
            if load.id in known or not is_light(load):
                continue
            known.add(load.id)
            new.append(WiserLight(coordinator, load))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserLight(WiserLoadEntity, LightEntity):
    """onoff / dim / dali(tw|rgb) light."""

    def __init__(self, coordinator: WiserCoordinator, load: Load) -> None:
        """Pick the color mode from the load type."""
        super().__init__(coordinator, load)
        if load.type is LoadType.ONOFF:
            mode = ColorMode.ONOFF
        elif load.type is LoadType.DALI and load.sub_type is LoadSubType.TW:
            mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = CT_MIN
            self._attr_max_color_temp_kelvin = CT_MAX
        elif load.type is LoadType.DALI and load.sub_type is LoadSubType.RGB:
            mode = ColorMode.RGBW
        else:
            mode = ColorMode.BRIGHTNESS
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

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
    def brightness(self) -> int | None:
        """0..255."""
        state = self.state_data
        return None if state is None else bri_to_brightness(state.bri)

    @property
    def color_temp_kelvin(self) -> int | None:
        """DALI tunable white."""
        state = self.state_data
        return None if state is None else state.ct

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """DALI RGBW."""
        state = self.state_data
        if state is None or state.red is None:
            return None
        return (state.red, state.green or 0, state.blue or 0, state.white or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw values."""
        state = self.state_data
        attrs: dict[str, Any] = {ATTR_LOAD_ID: self.load_id}
        if state is not None:
            attrs["bri_raw"] = state.bri
            if state.flags.has_problem:
                attrs["problem"] = True
        return attrs

    async def _target(self, **fields: int) -> None:
        try:
            await self.coordinator.client.set_target_state(self.load_id, **fields)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally with brightness / colour."""
        fields: dict[str, int] = {}
        if ATTR_BRIGHTNESS in kwargs:
            fields["bri"] = brightness_to_bri(kwargs[ATTR_BRIGHTNESS])
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            fields["ct"] = max(CT_MIN, min(CT_MAX, int(kwargs[ATTR_COLOR_TEMP_KELVIN])))
        if ATTR_RGBW_COLOR in kwargs:
            red, green, blue, white = kwargs[ATTR_RGBW_COLOR]
            fields.update(red=red, green=green, blue=blue, white=white)
        if "bri" not in fields:
            state = self.state_data
            if self._attr_color_mode is ColorMode.ONOFF or state is None or not state.bri:
                fields["bri"] = BRI_MAX
            else:
                fields["bri"] = state.bri
        await self._target(**fields)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._target(bri=0)

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
