"""Repair issues."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    ISSUE_BUTTONS_UNREGISTERED,
    ISSUE_DEVICE_DETAILS_FAILED,
    ISSUE_FIRMWARE_TOO_OLD,
    ISSUE_MOTOR_UNCALIBRATED,
    ISSUE_SERIAL_MISMATCH,
    MIN_FIRMWARE_BUTTONS,
    OPT_REGISTER_BUTTONS,
)
from .data import WiserConfigEntry
from .util import parse_version


@callback
def async_create_serial_mismatch_issue(
    hass: HomeAssistant, entry: WiserConfigEntry, found_sn: str
) -> None:
    """The host now answers with a different gateway."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_SERIAL_MISMATCH}_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_SERIAL_MISMATCH,
        translation_placeholders={
            "host": str(entry.data.get("host")),
            "expected": str(entry.unique_id),
            "found": found_sn,
        },
    )


@callback
def async_check_issues(hass: HomeAssistant, entry: WiserConfigEntry) -> None:
    """(Re)evaluate all condition-based issues after setup."""
    data = entry.runtime_data.coordinator.data
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_SERIAL_MISMATCH}_{entry.entry_id}")

    firmware_id = f"{ISSUE_FIRMWARE_TOO_OLD}_{entry.entry_id}"
    if data.info.sw and parse_version(data.info.sw) < MIN_FIRMWARE_BUTTONS:
        ir.async_create_issue(
            hass,
            DOMAIN,
            firmware_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FIRMWARE_TOO_OLD,
            translation_placeholders={
                "version": data.info.sw,
                "required": ".".join(str(x) for x in MIN_FIRMWARE_BUTTONS),
            },
            learn_more_url="https://github.com/Feller-AG/wiser-api/blob/main/CHANGELOG.md",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, firmware_id)

    buttons_id = f"{ISSUE_BUTTONS_UNREGISTERED}_{entry.entry_id}"
    sleeping = [b for b in data.buttons.values() if not b.registered]
    if sleeping and not entry.options.get(OPT_REGISTER_BUTTONS, True):
        ir.async_create_issue(
            hass,
            DOMAIN,
            buttons_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BUTTONS_UNREGISTERED,
            translation_placeholders={"count": str(len(sleeping))},
            data={"entry_id": entry.entry_id},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, buttons_id)

    for load in data.loads.values():
        issue_id = f"{ISSUE_MOTOR_UNCALIBRATED}_{entry.entry_id}_{load.id}"
        state = data.load_states.get(load.id)
        if load.is_motor and state is not None and state.flags.learning:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_MOTOR_UNCALIBRATED,
                translation_placeholders={"name": load.name or str(load.id)},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    details_id = f"{ISSUE_DEVICE_DETAILS_FAILED}_{entry.entry_id}"
    if data.details_failed:
        ir.async_create_issue(
            hass,
            DOMAIN,
            details_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DEVICE_DETAILS_FAILED,
            translation_placeholders={"devices": ", ".join(sorted(data.details_failed))},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, details_id)


class RegisterButtonsRepairFlow(RepairsFlow):
    """Confirm, then register every sleeping button."""

    def __init__(self, entry_id: str) -> None:
        """Remember the entry."""
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        """Show confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        """Register on confirm."""
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry is not None and hasattr(entry, "runtime_data"):
                from . import _async_register_buttons

                await _async_register_buttons(entry.runtime_data.coordinator)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str] | None
) -> RepairsFlow:
    """Return the fix flow for fixable issues."""
    return RegisterButtonsRepairFlow((data or {}).get("entry_id", ""))
