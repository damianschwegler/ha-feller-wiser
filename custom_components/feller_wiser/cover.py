"""Cover platform: blinds, shutters and awnings (Wiser ``motor`` loads)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    LEVEL_MAX,
    CtrlButton,
    CtrlEvent,
    Load,
    LoadSubType,
    LoadType,
    MotorKind,
    Moving,
    WiserApiError,
    WiserConnectionError,
)
from .const import (
    ATTR_KIND,
    ATTR_LEARNING,
    ATTR_LEVEL_RAW,
    ATTR_LOAD_ID,
    ATTR_LOCKED,
    ATTR_MOVING,
    ATTR_TILT_MS,
    ATTR_TILT_SOURCE,
    ATTR_TILT_STEPS,
    DOMAIN,
    SIGNAL_STRUCTURE_UPDATED,
)
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserLoadEntity
from .services import async_register_load_entity
from .tilt_controller import TiltController, TiltMode, TiltOptions
from .util import level_to_position, position_to_level, step_to_tilt_pct, tilt_pct_to_step

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
ASSUMED_MOVING_TTL_S = 3.0


def is_tiltable(coordinator: WiserCoordinator, load: Load) -> bool:
    """Device config is authoritative; ``kind`` is the fallback."""
    config = coordinator.data.motor_config(load)
    if config is not None and config.tiltable is not None:
        return config.tiltable
    return load.kind == MotorKind.VENETIAN_BLINDS


def cover_device_class(load: Load, tiltable: bool) -> CoverDeviceClass:
    """Map the app ``kind`` to a HA device class."""
    if load.kind == MotorKind.AWNINGS:
        return CoverDeviceClass.AWNING
    if load.kind == MotorKind.ROLLER_SHUTTERS:
        return CoverDeviceClass.SHUTTER
    if tiltable or load.kind == MotorKind.VENETIAN_BLINDS:
        return CoverDeviceClass.BLIND
    return CoverDeviceClass.SHADE


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one cover per motor load; add new ones after a structure reload."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new: list[WiserCover] = []
        for load in coordinator.data.loads.values():
            if load.type is not LoadType.MOTOR or load.id in known:
                continue
            known.add(load.id)
            new.append(WiserCover(coordinator, entry, load))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserCover(WiserLoadEntity, CoverEntity):
    """A Wiser motor load. Features depend on relay/tiltable configuration."""

    def __init__(self, coordinator: WiserCoordinator, entry: WiserConfigEntry, load: Load) -> None:
        """Set up features and the tilt controller."""
        super().__init__(coordinator, load)
        self._entry = entry
        self._assumed_moving: Moving | None = None
        self._assumed_until = 0.0
        self._tracking: asyncio.Task[None] | None = None
        self._tilt: TiltController | None = None
        self._refresh_capabilities()

    # ------------------------------------------------------------------ capabilities
    @callback
    def _refresh_capabilities(self) -> None:
        load = self.load
        relay = load.sub_type is LoadSubType.RELAY
        tiltable = not relay and is_tiltable(self.coordinator, load)
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if not relay:
            features |= CoverEntityFeature.SET_POSITION
        if tiltable:
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.STOP_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
        self._attr_supported_features = features
        self._attr_device_class = cover_device_class(load, tiltable)
        self._tiltable = tiltable
        if tiltable and self._tilt is None:
            self._tilt = self._entry.runtime_data.tilt_controllers.get(load.id)
            if self._tilt is None:
                self._tilt = TiltController(
                    self.hass if self.hass else self.coordinator.hass,
                    self.coordinator,
                    load.id,
                    lambda: TiltOptions.from_options(dict(self._entry.options)),
                )
                self._entry.runtime_data.tilt_controllers[load.id] = self._tilt

    @property
    def tiltable(self) -> bool:
        """True for venetian blinds."""
        return self._tiltable

    @property
    def tilt_controller(self) -> TiltController | None:
        """The controller used by services and the number entity."""
        return self._tilt

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_capabilities()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Register for services."""
        await super().async_added_to_hass()
        self.async_on_remove(async_register_load_entity(self.hass, self))
        self._refresh_capabilities()

    async def async_will_remove_from_hass(self) -> None:
        """Stop background work."""
        if self._tracking is not None:
            self._tracking.cancel()
        if self._tilt is not None:
            await self._tilt.cancel()
        await super().async_will_remove_from_hass()

    # ------------------------------------------------------------------ state
    @property
    def _moving(self) -> Moving | None:
        state = self.state_data
        if state is not None and state.moving is not None and state.moving is not Moving.STOP:
            return state.moving
        if self._assumed_moving is not None and time.monotonic() < self._assumed_until:
            return self._assumed_moving
        return None

    @property
    def current_cover_position(self) -> int | None:
        """100 = open."""
        state = self.state_data
        if state is None or state.flags.learning:
            return None
        return level_to_position(state.level)

    @property
    def current_cover_tilt_position(self) -> int | None:
        """100 = slats horizontal."""
        state = self.state_data
        if not self._tiltable or state is None or state.flags.learning:
            return None
        return step_to_tilt_pct(state.tilt)

    @property
    def is_opening(self) -> bool:
        """Moving up."""
        return self._moving is Moving.UP

    @property
    def is_closing(self) -> bool:
        """Moving down."""
        return self._moving is Moving.DOWN

    @property
    def is_closed(self) -> bool | None:
        """Fully down."""
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def assumed_state(self) -> bool:
        """Uncalibrated motors do not know their position."""
        state = self.state_data
        return bool(state and state.flags.learning)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw Wiser values for automations."""
        state = self.state_data
        config = self.data.motor_config(self.load)
        attrs: dict[str, Any] = {
            ATTR_LOAD_ID: self.load_id,
            ATTR_KIND: self.load.kind,
            ATTR_LEVEL_RAW: state.level if state else None,
            ATTR_MOVING: str(state.moving) if state and state.moving else None,
            ATTR_LEARNING: bool(state.flags.learning) if state else None,
            ATTR_LOCKED: bool(state.flags.locked) if state else None,
        }
        if self._tiltable:
            attrs[ATTR_TILT_STEPS] = state.tilt if state else None
            attrs[ATTR_TILT_MS] = config.tilt_ms if config else None
            attrs[ATTR_TILT_SOURCE] = "config" if config and config.tiltable is not None else "kind"
        return attrs

    # ------------------------------------------------------------------ commands
    def _guard(self, *, allow_learning: bool) -> None:
        state = self.state_data
        if state is None:
            return
        if state.flags.locked:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="blind_locked")
        if state.flags.learning and not allow_learning:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="motor_learning")

    async def _cancel_tilt(self) -> None:
        if self._tilt is not None:
            await self._tilt.cancel()

    def _assume(self, moving: Moving | None) -> None:
        self._assumed_moving = moving
        self._assumed_until = time.monotonic() + ASSUMED_MOVING_TTL_S
        self.async_write_ha_state()
        if moving is not None:
            self._start_tracking()

    def _start_tracking(self) -> None:
        """Poll the single load while it moves and the websocket is down."""
        if self.data.ws_connected:
            return
        if self._tracking is not None and not self._tracking.done():
            return
        self._tracking = self._entry.async_create_background_task(
            self.hass, self._track_movement(), f"{DOMAIN}-track-{self.load_id}"
        )

    async def _track_movement(self) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            try:
                state = await self.coordinator.client.get_load_state(self.load_id)
            except WiserApiError, WiserConnectionError:
                return
            self.coordinator.async_set_load_state(self.load_id, state)
            if not state.is_moving:
                return

    async def _target(self, **fields: int) -> None:
        try:
            await self.coordinator.client.set_target_state(self.load_id, **fields)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _ctrl(self, button: CtrlButton, event: CtrlEvent) -> None:
        try:
            await self.coordinator.client.ctrl(self.load_id, button, event)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Run fully up."""
        self._guard(allow_learning=True)
        await self._cancel_tilt()
        await self._target(level=0)
        self._assume(Moving.UP)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Run fully down."""
        self._guard(allow_learning=True)
        await self._cancel_tilt()
        await self._target(level=LEVEL_MAX)
        self._assume(Moving.DOWN)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Run to a position (100 = open)."""
        self._guard(allow_learning=False)
        await self._cancel_tilt()
        level = position_to_level(int(kwargs[ATTR_POSITION]))
        state = self.state_data
        await self._target(level=level)
        if state is not None and state.level is not None and state.level != level:
            self._assume(Moving.DOWN if level > state.level else Moving.UP)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop any movement."""
        await self._cancel_tilt()
        await self._ctrl(CtrlButton.STOP, CtrlEvent.CLICK)
        self._assume(None)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Slats horizontal (step 9)."""
        await self.async_set_tilt_steps(9)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Slats closed (step 0, reference run)."""
        await self.async_set_tilt_steps(0)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Tilt to a percentage (100 = horizontal)."""
        await self.async_set_tilt_steps(tilt_pct_to_step(int(kwargs[ATTR_TILT_POSITION])))

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop a running tilt."""
        await self.async_stop_cover()

    async def async_set_tilt_steps(
        self,
        steps: int,
        mode: TiltMode = TiltMode.AUTO,
        *,
        wait: bool = True,
        max_rounds: int | None = None,
    ) -> dict[str, Any]:
        """Tilt in raw Wiser steps; returns the outcome for service responses."""
        if not self._tiltable or self._tilt is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_tiltable")
        self._guard(allow_learning=False)
        outcome = await self._tilt.set_steps(steps, mode, wait=wait, max_rounds=max_rounds)
        self.async_write_ha_state()
        return outcome.as_dict()

    async def async_set_target_state(self, level: int | None, tilt: int | None) -> None:
        """Raw target_state (service)."""
        await self._cancel_tilt()
        fields: dict[str, int] = {}
        if level is not None:
            fields["level"] = level
        if tilt is not None:
            fields["tilt"] = tilt
        await self._target(**fields)
        state = self.state_data
        if (
            level is not None
            and state is not None
            and state.level is not None
            and state.level != level
        ):
            self._assume(Moving.DOWN if level > state.level else Moving.UP)
        elif tilt is not None:
            self._assume(Moving.DOWN)

    async def async_load_ctrl(self, button: str, event: str) -> None:
        """Raw ctrl (service), no guards."""
        await self._cancel_tilt()
        await self._ctrl(CtrlButton(button), CtrlEvent(event))
        if event == "press" and button in ("up", "down"):
            self._assume(Moving.UP if button == "up" else Moving.DOWN)
