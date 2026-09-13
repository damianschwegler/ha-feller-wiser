"""Config flow: manual, discovery, claim progress, reauth, reconfigure, options."""

from ipaddress import ip_address
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import (
    CONF_SERIAL,
    CONF_SOURCE,
    CONF_TOKEN,
    CONF_USERNAME,
    DOMAIN,
    OPT_POLL_INTERVAL,
)
from tests.conftest import SimHandle
from tests.const import TEST_SN, TEST_TOKEN, TEST_USER


async def _finish_claim(hass: HomeAssistant, simulator: SimHandle, flow_id: str) -> dict:
    await simulator.wait_until(lambda: simulator.model.claim.active)
    simulator.press_button()
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(flow_id)


async def test_user_flow(hass: HomeAssistant, simulator: SimHandle) -> None:
    with patch("custom_components.feller_wiser.async_setup_entry", return_value=True) as setup:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: f"http://{simulator.host}/"}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["step_id"] == "claim"
        assert result["progress_action"] == "claim_press_button"

        result = await _finish_claim(hass, simulator, result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Zuhause"
        assert result["data"][CONF_HOST] == simulator.host
        assert result["data"][CONF_USERNAME] == TEST_USER
        assert result["data"][CONF_SOURCE] == "admin"
        assert result["data"][CONF_SERIAL] == TEST_SN
        assert result["data"][CONF_TOKEN] in simulator.model.tokens
        assert result["result"].unique_id == TEST_SN
        await hass.async_block_till_done()
        assert setup.call_count == 1


async def test_user_flow_source_fallback(hass: HomeAssistant, simulator: SimHandle) -> None:
    del simulator.model.accounts["admin"]
    with patch("custom_components.feller_wiser.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data={CONF_HOST: simulator.host}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        result = await _finish_claim(hass, simulator, result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_SOURCE] == "installer"


async def test_user_flow_errors(
    hass: HomeAssistant, simulator: SimHandle, unused_tcp_port: int
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_HOST: f"127.0.0.1:{unused_tcp_port}"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_claim_timeout_then_retry(hass: HomeAssistant, simulator: SimHandle) -> None:
    with patch("custom_components.feller_wiser.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data={CONF_HOST: simulator.host}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        # nobody presses: the simulator times out after 2 s
        await simulator.wait_until(lambda: not simulator.model.claim.active, timeout=5)
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "claim_failed"
        assert result["errors"] == {"base": "claim_timeout"}
        # retry
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        result = await _finish_claim(hass, simulator, result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_zeroconf_flow(hass: HomeAssistant, simulator: SimHandle) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname="wiser-00429931.local.",
        name="wiser-00429931._http._tcp.local.",
        port=simulator.server.port,
        properties={},
        type="_http._tcp.local.",
    )
    with patch("custom_components.feller_wiser.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"
        assert result["description_placeholders"]["sn"] == TEST_SN
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        result = await _finish_claim(hass, simulator, result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOST] == simulator.host


async def test_dhcp_flow_updates_existing_host(hass: HomeAssistant, simulator: SimHandle) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SN,
        data={CONF_HOST: "192.0.2.1", CONF_TOKEN: TEST_TOKEN},
    )
    entry.add_to_hass(hass)
    # the dhcp step only carries an ip; our simulator runs on a port, so patch the probe host
    info = DhcpServiceInfo(ip=simulator.host, hostname="wiser-00429931", macaddress="020304050607")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == simulator.host


async def test_reauth_flow(
    hass: HomeAssistant, live_simulator: SimHandle, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    live_simulator.model.revoke_all_tokens()
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await _finish_claim(hass, live_simulator, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_TOKEN] != TEST_TOKEN
    assert entry.data[CONF_TOKEN] in live_simulator.model.tokens


async def test_reconfigure_flow(
    hass: HomeAssistant, live_simulator: SimHandle, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"http://{live_simulator.host}"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_options_flow(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPT_POLL_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[OPT_POLL_INTERVAL] == 60
