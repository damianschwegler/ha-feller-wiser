"""Climate platform: Wiser HVAC groups (thermostat + valve channels)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HvacState, WiserApiError, WiserConnectionError
from .const import DOMAIN, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserGatewayEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create climate entities."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = []
        for group in coordinator.data.hvac_groups.values():
            if group.id in known:
                continue
            known.add(group.id)
            new.append(WiserClimate(coordinator, group.id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserClimate(WiserGatewayEntity, ClimateEntity):
    """Target temperature of an HVAC group."""

    _attr_entity_category = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0

    def __init__(self, coordinator: WiserCoordinator, group_id: int) -> None:
        """Unique id ``{sn}_hvac_{id}``."""
        super().__init__(coordinator, f"hvac_{group_id}")
        self._group_id = group_id

    @property
    def _state(self) -> HvacState | None:
        return self.data.hvac_states.get(self._group_id)

    @property
    def name(self) -> str:
        """Group name."""
        group = self.data.hvac_groups.get(self._group_id)
        return group.name if group and group.name else f"Heizung {self._group_id}"

    @property
    def available(self) -> bool:
        """Only while the group exists and has a state."""
        return (
            super().available
            and self._group_id in self.data.hvac_groups
            and self._state is not None
        )

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Heating (or cooling) only; the gateway has no off mode via API."""
        state = self._state
        return [HVACMode.COOL if state and state.cooling else HVACMode.HEAT]

    @property
    def hvac_mode(self) -> HVACMode:
        """Current mode."""
        return self.hvac_modes[0]

    @property
    def hvac_action(self) -> HVACAction | None:
        """Whether the valve is open."""
        state = self._state
        if state is None:
            return None
        if state.output_on:
            return HVACAction.COOLING if state.cooling else HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Ambient temperature."""
        state = self._state
        return None if state is None else state.ambient_temperature

    @property
    def target_temperature(self) -> float | None:
        """Set point."""
        state = self._state
        return None if state is None else state.target_temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Flags."""
        state = self._state
        return {"hvac_group_id": self._group_id, **(state.flags if state else {})}

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        try:
            await self.coordinator.client.set_hvac_target(self._group_id, float(temperature))
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err
        state = self._state
        if state is not None:
            self.data.hvac_states[self._group_id] = state.merge(
                {"target_temperature": float(temperature)}
            )
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Mode cannot be changed through the API."""
