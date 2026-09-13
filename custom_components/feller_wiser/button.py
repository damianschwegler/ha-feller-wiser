"""Button platform: identify a load, refresh the structure, re-read motor configuration."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Load, WiserApiError, WiserConnectionError
from .const import DOMAIN, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserGatewayEntity, WiserLoadEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create button entities."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    async_add_entities(
        [WiserRefreshStructureButton(coordinator), WiserReloadMotorConfigButton(coordinator)]
    )

    @callback
    def _add_new() -> None:
        new = []
        for load in coordinator.data.loads.values():
            if load.id in known:
                continue
            known.add(load.id)
            new.append(WiserIdentifyButton(coordinator, load))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserIdentifyButton(WiserLoadEntity, ButtonEntity):
    """Flash the button LED of the load."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "identify"

    def __init__(self, coordinator: WiserCoordinator, load: Load) -> None:
        """Unique id ``{device}_{channel}_identify``."""
        super().__init__(coordinator, load, "_identify")

    async def async_press(self) -> None:
        """Ping."""
        try:
            await self.coordinator.client.ping_load(self.load_id)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err


class WiserRefreshStructureButton(WiserGatewayEntity, ButtonEntity):
    """Re-read loads, rooms, devices, scenes."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "refresh_structure"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: WiserCoordinator) -> None:
        """Unique id ``{sn}_refresh_structure``."""
        super().__init__(coordinator, "refresh_structure")

    async def async_press(self) -> None:
        """Reload."""
        await self.coordinator.async_load_structure()
        await self.coordinator.async_request_refresh()


class WiserReloadMotorConfigButton(WiserGatewayEntity, ButtonEntity):
    """Forget cached device details and read them again."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reload_motor_config"
    _attr_icon = "mdi:cog-refresh"

    def __init__(self, coordinator: WiserCoordinator) -> None:
        """Unique id ``{sn}_reload_motor_config``."""
        super().__init__(coordinator, "reload_motor_config")

    async def async_press(self) -> None:
        """Reload in the background."""
        await self.coordinator.async_reload_motor_configs()
