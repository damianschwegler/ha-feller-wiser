"""Base entities."""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import Load, LoadState
from .const import DEFAULT_ROOMS_AS_AREAS, OPT_ROOMS_AS_AREAS
from .coordinator import WiserCoordinator
from .data import WiserData
from .naming import gateway_device_info, gateway_registry_id, load_entity_name, wiser_device_info


class WiserEntity(CoordinatorEntity[WiserCoordinator]):
    """Common base: names come from the device, state changes are compared before writing."""

    _attr_has_entity_name = True

    @property
    def data(self) -> WiserData:
        """Shortcut to the coordinator data."""
        return self.coordinator.data

    @property
    def rooms_as_areas(self) -> bool:
        """Whether Wiser rooms should be suggested as HA areas."""
        return bool(
            self.coordinator.config_entry.options.get(OPT_ROOMS_AS_AREAS, DEFAULT_ROOMS_AS_AREAS)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class WiserGatewayEntity(WiserEntity):
    """Entity attached to the gateway device (diagnostics, flags, scenes, ...)."""

    _attr_entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WiserCoordinator, key: str) -> None:
        """Set unique id ``{sn}_{key}``."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.data.info.sn}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """The gateway."""
        return gateway_device_info(self.data, self.coordinator.client.host)


class WiserLoadEntity(WiserEntity):
    """Entity bound to one load (output channel of a device)."""

    def __init__(self, coordinator: WiserCoordinator, load: Load, suffix: str = "") -> None:
        """Set unique id ``{device}_{channel}{suffix}`` and device info."""
        super().__init__(coordinator)
        self._load_id = load.id
        self._attr_unique_id = f"{load.unique_key}{suffix}"
        data = coordinator.data
        if not suffix and getattr(self, "_attr_translation_key", None) is None:
            self._attr_name = load_entity_name(data, load, data.devices.get(load.device))
        # Suggest a stable, readable entity id from the Wiser load name ("Büro" -> cover.buro).
        # Home Assistant only uses it for the first registration; user renames win afterwards.
        domain = type(self).__module__.rsplit(".", 1)[-1]
        base = load.name.strip()
        if not base or base.startswith(load.device):
            room = data.room_name(load.room) or "wiser"
            base = f"{room} {load.raw_type}"
        self.entity_id = f"{domain}.{slugify(base)}{suffix}"

    @property
    def load(self) -> Load:
        """Current load description (may be refreshed on structure reload)."""
        return self.data.loads[self._load_id]

    @property
    def load_id(self) -> int:
        """Wiser load id."""
        return self._load_id

    @property
    def state_data(self) -> LoadState | None:
        """Current state of the load, ``None`` until first fetched."""
        return self.data.load_states.get(self._load_id)

    @property
    def available(self) -> bool:
        """Available once we have a state and the last poll succeeded."""
        return (
            super().available
            and self._load_id in self.data.loads
            and self._load_id in self.data.load_states
        )

    @property
    def device_info(self) -> DeviceInfo:
        """The physical Wiser device driving this load."""
        device = self.data.devices.get(self.load.device)
        if device is None:
            from .api import Device

            device = Device.from_api({"id": self.load.device})
        return wiser_device_info(
            self.data,
            device,
            rooms_as_areas=self.rooms_as_areas,
            via_device_id=gateway_registry_id(self.hass, self.data),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to per-load updates in addition to the coordinator."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_load_listener(self._load_id, self._handle_load_update)
        )

    @callback
    def _handle_load_update(self) -> None:
        self.async_write_ha_state()
