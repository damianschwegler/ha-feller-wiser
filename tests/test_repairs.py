"""Repair issues raised by the integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import (
    DOMAIN,
    ISSUE_FIRMWARE_TOO_OLD,
    ISSUE_MOTOR_UNCALIBRATED,
    ISSUE_SERIAL_MISMATCH,
)
from tests.conftest import SimHandle


async def test_no_issues_on_healthy_gateway(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    registry = ir.async_get(hass)
    ours = [issue for (domain, _), issue in registry.issues.items() if domain == DOMAIN]
    assert ours == []


async def test_firmware_too_old_issue(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.model.info["sw"] = "6.0.33"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(
        DOMAIN, f"{ISSUE_FIRMWARE_TOO_OLD}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["version"] == "6.0.33"
    await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_uncalibrated_motor_issue(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.model.loads[64].flags["learning"] = 1
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(
        DOMAIN, f"{ISSUE_MOTOR_UNCALIBRATED}_{mock_config_entry.entry_id}_64"
    )
    assert issue is not None
    state = hass.states.get("cover.buro")
    assert state is not None
    assert state.attributes.get("assumed_state") is True
    assert "current_position" not in state.attributes
    await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_serial_mismatch_issue(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.model.info["sn"] = "12345678"
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(
        DOMAIN, f"{ISSUE_SERIAL_MISMATCH}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["found"] == "12345678"
