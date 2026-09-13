"""Integration services.

Entities register themselves at runtime so one service can target covers, lights and
switches alike without one platform owning the service.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_entity_ids
import voluptuous as vol

from .api import LEVEL_MAX, TILT_MAX
from .const import (
    DOMAIN,
    SERVICE_LOAD_CTRL,
    SERVICE_REFRESH_STRUCTURE,
    SERVICE_SET_TARGET_STATE,
    SERVICE_SET_TILT_STEPS,
)

if TYPE_CHECKING:
    from .entity import WiserLoadEntity

_LOGGER = logging.getLogger(__name__)

DATA_ENTITIES = f"{DOMAIN}_load_entities"

ATTR_STEPS = "steps"
ATTR_MODE = "mode"
ATTR_MAX_ROUNDS = "max_rounds"
ATTR_WAIT = "wait"
ATTR_LEVEL = "level"
ATTR_TILT = "tilt"
ATTR_BUTTON = "button"
ATTR_EVENT = "event"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

SET_TILT_STEPS_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_STEPS): vol.All(vol.Coerce(int), vol.Range(-TILT_MAX, TILT_MAX)),
        vol.Optional(ATTR_MODE, default="auto"): vol.In(
            ["auto", "absolute", "relative", "reference"]
        ),
        vol.Optional(ATTR_MAX_ROUNDS): vol.All(vol.Coerce(int), vol.Range(1, 5)),
        vol.Optional(ATTR_WAIT, default=True): cv.boolean,
    }
)
SET_TARGET_STATE_SCHEMA = vol.All(
    cv.make_entity_service_schema(
        {
            vol.Optional(ATTR_LEVEL): vol.All(vol.Coerce(int), vol.Range(0, LEVEL_MAX)),
            vol.Optional(ATTR_TILT): vol.All(vol.Coerce(int), vol.Range(0, TILT_MAX)),
        }
    ),
    cv.has_at_least_one_key(ATTR_LEVEL, ATTR_TILT),
)
LOAD_CTRL_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_BUTTON): vol.In(["up", "down", "stop", "toggle", "on", "off"]),
        vol.Optional(ATTR_EVENT, default="click"): vol.In(["click", "press", "release"]),
    }
)
REFRESH_STRUCTURE_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


@callback
def async_register_load_entity(hass: HomeAssistant, entity: WiserLoadEntity) -> Callable[[], None]:
    """Make an entity reachable for the services; returns the unregister callback."""
    registry: dict[str, WiserLoadEntity] = hass.data.setdefault(DATA_ENTITIES, {})
    entity_id = entity.entity_id
    registry[entity_id] = entity

    def _unregister() -> None:
        if registry.get(entity_id) is entity:
            del registry[entity_id]

    return _unregister


async def _targets(hass: HomeAssistant, call: ServiceCall) -> list[WiserLoadEntity]:
    registry: dict[str, WiserLoadEntity] = hass.data.get(DATA_ENTITIES, {})
    entity_ids = await async_extract_entity_ids(call)
    entities = [registry[eid] for eid in sorted(entity_ids) if eid in registry]
    if not entities:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_target_entities"
        )
    return entities


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register all services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_TILT_STEPS):
        return

    async def _set_tilt_steps(call: ServiceCall) -> ServiceResponse:
        from .cover import WiserCover
        from .tilt_controller import TiltMode

        steps: int = call.data[ATTR_STEPS]
        mode = TiltMode(call.data[ATTR_MODE])
        if steps < 0 and mode is not TiltMode.RELATIVE:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="negative_steps_absolute"
            )
        results: dict[str, Any] = {}
        for entity in await _targets(hass, call):
            if not isinstance(entity, WiserCover):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_tiltable",
                    translation_placeholders={"entity_id": entity.entity_id},
                )
            results[entity.entity_id] = await entity.async_set_tilt_steps(
                steps, mode, wait=call.data[ATTR_WAIT], max_rounds=call.data.get(ATTR_MAX_ROUNDS)
            )
        return results if call.return_response else None

    async def _set_target_state(call: ServiceCall) -> None:
        from .cover import WiserCover

        for entity in await _targets(hass, call):
            if not isinstance(entity, WiserCover):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_a_cover",
                    translation_placeholders={"entity_id": entity.entity_id},
                )
            await entity.async_set_target_state(call.data.get(ATTR_LEVEL), call.data.get(ATTR_TILT))

    async def _load_ctrl(call: ServiceCall) -> None:
        for entity in await _targets(hass, call):
            handler = getattr(entity, "async_load_ctrl", None)
            if handler is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_ctrl_support",
                    translation_placeholders={"entity_id": entity.entity_id},
                )
            await handler(call.data[ATTR_BUTTON], call.data[ATTR_EVENT])

    async def _refresh_structure(call: ServiceCall) -> None:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if entry_id:
            entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_config_entry"
            )
        for entry in entries:
            coordinator = entry.runtime_data.coordinator
            await coordinator.async_load_structure()
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TILT_STEPS,
        _set_tilt_steps,
        schema=SET_TILT_STEPS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TARGET_STATE, _set_target_state, schema=SET_TARGET_STATE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_LOAD_CTRL, _load_ctrl, schema=LOAD_CTRL_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH_STRUCTURE, _refresh_structure, schema=REFRESH_STRUCTURE_SCHEMA
    )
