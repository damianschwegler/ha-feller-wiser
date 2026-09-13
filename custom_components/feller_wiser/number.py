"""Number platform: raw tilt step (0..9) of venetian blinds."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import TILT_MAX, Load, LoadType
from .const import SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .cover import is_tiltable
from .data import WiserConfigEntry
from .entity import WiserLoadEntity
from .tilt_controller import TiltController, TiltMode, TiltOptions

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One tilt-step number per tiltable blind."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = []
        for load in coordinator.data.loads.values():
            if load.type is not LoadType.MOTOR or load.id in known:
                continue
            if not is_tiltable(coordinator, load):
                continue
            known.add(load.id)
            new.append(WiserTiltStepNumber(coordinator, entry, load))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserTiltStepNumber(WiserLoadEntity, NumberEntity):
    """Discrete slat position in Wiser steps (0 = closed, 9 = horizontal)."""

    _attr_translation_key = "tilt_step"
    _attr_native_min_value = 0
    _attr_native_max_value = TILT_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:blinds-horizontal"

    def __init__(self, coordinator: WiserCoordinator, entry: WiserConfigEntry, load: Load) -> None:
        """Share the tilt controller with the cover entity."""
        super().__init__(coordinator, load, "_tilt_step")
        self._entry = entry

    def _controller(self) -> TiltController:
        controllers = self._entry.runtime_data.tilt_controllers
        controller = controllers.get(self.load_id)
        if controller is None:
            controller = TiltController(
                self.hass,
                self.coordinator,
                self.load_id,
                lambda: TiltOptions.from_options(dict(self._entry.options)),
            )
            controllers[self.load_id] = controller
        return controller

    @property
    def native_value(self) -> float | None:
        """Current step."""
        state = self.state_data
        return None if state is None or state.tilt is None else float(state.tilt)

    async def async_set_native_value(self, value: float) -> None:
        """Tilt via clicks (auto mode)."""
        await self._controller().set_steps(int(value), TiltMode.AUTO)
        self.async_write_ha_state()
