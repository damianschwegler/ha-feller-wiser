"""Device triggers for physical buttons (click / press / release per channel)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_EVENT_DATA,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .api import ButtonEventType
from .const import DOMAIN, EVENT_BUTTON

CONF_SUBTYPE = "subtype"
TRIGGER_TYPES = {str(x) for x in ButtonEventType}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Required(CONF_SUBTYPE): cv.string,
    }
)


def _wiser_device_id(hass: HomeAssistant, device_id: str) -> str | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain == DOMAIN:
            return ident
    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """List click/press/release triggers for every registered button of the device."""
    wiser_id = _wiser_device_id(hass, device_id)
    if wiser_id is None:
        return []
    triggers: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        data = entry.runtime_data.coordinator.data
        for button in data.buttons.values():
            if button.device != wiser_id or not button.registered:
                continue
            triggers.extend(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: trigger_type,
                    CONF_SUBTYPE: f"button_{button.channel + 1}",
                }
                for trigger_type in sorted(TRIGGER_TYPES)
            )
    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach an event trigger on the integration's button event."""
    channel = int(str(config[CONF_SUBTYPE]).rsplit("_", 1)[1]) - 1
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_BUTTON,
            CONF_EVENT_DATA: {
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                "channel": channel,
                "type": config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
