"""Event platform: physical button presses of registered buttons."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Button, ButtonEventType, Device
from .const import SIGNAL_BUTTON_EVENT, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserEntity
from .naming import gateway_registry_id, wiser_device_info

PARALLEL_UPDATES = 0

EVENT_TYPES = [str(x) for x in ButtonEventType]


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One event entity per registered button."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for button in coordinator.data.buttons.values():
            if button.unique_key in known or not button.registered:
                continue
            known.add(button.unique_key)
            new.append(WiserButtonEvent(coordinator, entry, button))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )
    # buttons registered after setup arrive through a listener update
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WiserButtonEvent(WiserEntity, EventEntity):
    """click / press / release of one wall button."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "button"

    def __init__(
        self, coordinator: WiserCoordinator, entry: WiserConfigEntry, button: Button
    ) -> None:
        """Unique id ``{device}_button_{channel}``."""
        super().__init__(coordinator)
        self._entry = entry
        self._key = button.unique_key
        self._device_id = button.device
        self._channel = button.channel
        self._attr_unique_id = button.unique_key
        self._attr_translation_placeholders = {"channel": str(button.channel + 1)}

    @property
    def button(self) -> Button | None:
        """Current button object."""
        return self.data.buttons.get(self._key)

    @property
    def available(self) -> bool:
        """Only while registered."""
        button = self.button
        return super().available and button is not None and button.registered

    @property
    def device_info(self) -> DeviceInfo:
        """The control front the button belongs to."""
        device = self.data.devices.get(self._device_id) or Device.from_api({"id": self._device_id})
        return wiser_device_info(
            self.data,
            device,
            rooms_as_areas=self.rooms_as_areas,
            via_device_id=gateway_registry_id(self.hass, self.data),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Wiser ids."""
        button = self.button
        return {
            "button_id": button.id if button else None,
            "channel": self._channel,
            "button_type": button.sub_type if button else None,
        }

    async def async_added_to_hass(self) -> None:
        """Listen for events of this button id."""
        await super().async_added_to_hass()
        button = self.button
        if button is None or button.id is None:
            return
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_BUTTON_EVENT.format(f"{self._entry.entry_id}_{button.id}"),
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type", "click"))
        if event_type not in EVENT_TYPES:
            return
        self._trigger_event(event_type, {"button_type": payload.get("button_type")})
        self.async_write_ha_state()
