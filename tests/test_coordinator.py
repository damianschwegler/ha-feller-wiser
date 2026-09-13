"""Websocket / polling behaviour of the coordinator and diagnostics output."""

import asyncio
from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.feller_wiser.const import POLL_INTERVAL_WS_DOWN
from custom_components.feller_wiser.diagnostics import async_get_config_entry_diagnostics
from tests.conftest import SimHandle


async def test_ws_down_switches_to_fast_polling(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    coordinator = setup_integration.runtime_data.coordinator
    await live_simulator.wait_until(lambda: coordinator.data.ws_connected)
    await live_simulator.hub.disconnect_all()
    await live_simulator.wait_until(lambda: not coordinator.data.ws_connected)
    assert coordinator.update_interval == timedelta(seconds=POLL_INTERVAL_WS_DOWN)
    await live_simulator.wait_until(lambda: coordinator.data.ws_connected, timeout=10)
    assert coordinator.update_interval > timedelta(seconds=POLL_INTERVAL_WS_DOWN)


async def test_reboot_resyncs_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    coordinator = setup_integration.runtime_data.coordinator
    await live_simulator.wait_until(lambda: coordinator.data.ws_connected)
    live_simulator.faults.reject_api = True
    await live_simulator.hub.disconnect_all()
    await live_simulator.wait_until(lambda: not coordinator.data.ws_connected)
    # state changes while we are disconnected
    live_simulator.model.loads[64].tilt = 1
    live_simulator.faults.reject_api = False
    await live_simulator.wait_until(lambda: coordinator.data.ws_connected, timeout=10)
    await live_simulator.wait_until(lambda: coordinator.data.load_states[64].tilt == 1, timeout=10)
    assert setup_integration.runtime_data.websocket.stats.connects >= 2


async def test_revoked_token_on_ws_starts_reauth(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    coordinator = setup_integration.runtime_data.coordinator
    await live_simulator.wait_until(lambda: coordinator.data.ws_connected)
    live_simulator.model.revoke_all_tokens()
    await live_simulator.hub.disconnect_all()
    await live_simulator.wait_until(
        lambda: any(
            f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
        ),
        timeout=10,
    )


async def test_diagnostics(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    live_simulator: SimHandle,
    snapshot: SnapshotAssertion,
) -> None:
    await live_simulator.wait_until(
        lambda: setup_integration.runtime_data.coordinator.data.details_complete, timeout=15
    )
    await asyncio.sleep(0)
    diag = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert diag["net"]["mac_addr"] == "**REDACTED**"
    assert diag["counts"]["loads"] == 16
    assert diag["motor_configs"]["00001001_0"]["tilt_ms"] == 300
    assert diag["websocket"]["connects"] >= 1
    stable = {
        k: diag[k]
        for k in ("loads", "rooms", "scenes", "sensors", "flags", "motor_configs", "counts")
    }
    assert stable == snapshot
