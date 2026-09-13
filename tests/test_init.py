"""Setup / unload of the config entry."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import DOMAIN
from tests.conftest import SimHandle
from tests.const import TEST_SN


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime.coordinator.data.info.sn == TEST_SN
    await live_simulator.wait_until(lambda: runtime.coordinator.data.ws_connected)

    dev_reg = dr.async_get(hass)
    gateway = dev_reg.async_get_device_by_identifier((DOMAIN, TEST_SN), entry.entry_id)
    assert gateway is not None
    assert gateway.manufacturer == "Feller AG"
    assert gateway.name == "Zuhause"
    blind_device = dev_reg.async_get_device_by_identifier((DOMAIN, "00001001"), entry.entry_id)
    assert blind_device is not None
    assert blind_device.name == "Büro"
    assert blind_device.area_id is not None
    assert blind_device.via_device_id == gateway.id

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    domains = {e.domain for e in entities}
    assert {
        "cover",
        "light",
        "switch",
        "scene",
        "sensor",
        "binary_sensor",
        "climate",
        "event",
        "button",
        "number",
    } <= domains
    assert len([e for e in entities if e.domain == "cover"]) == 11

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not runtime.websocket.connected


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.faults.reject_api = True
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_bad_token_starts_reauth(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.model.revoke_all_tokens()
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["context"]["source"] == "reauth"


async def test_setup_wrong_serial(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> None:
    live_simulator.model.info["sn"] = "99999999"
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
