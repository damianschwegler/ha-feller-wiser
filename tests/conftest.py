"""Shared fixtures: a simulated µGateway on an ephemeral port plus HA helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import sys
from typing import Any

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest_socket

from custom_components.feller_wiser.const import (
    CONF_SERIAL,
    CONF_SOURCE,
    CONF_TOKEN,
    CONF_USERNAME,
    DOMAIN,
    OPT_CLICK_MARGIN_MS,
    OPT_FALLBACK_CLICK_PAUSE_MS,
    OPT_TILT_SETTLE_MS,
)
from simulator.app import create_app
from simulator.faults import FaultConfig
from simulator.model import FIXTURES, GatewayModel, SimConfig
from simulator.ws import WsHub
from tests.const import TEST_SN, TEST_TOKEN, TEST_USER

pytest_plugins = ["pytest_homeassistant_custom_component"]

if sys.platform == "win32":
    # The asyncio self-pipe is an AF_INET socketpair on Windows, which pytest-socket blocks
    # (on Linux it is AF_UNIX and allowed). Local Windows runs therefore keep sockets enabled;
    # the dev container and CI run on Linux with the strict Home Assistant behaviour.
    pytest_socket.disable_socket = lambda allow_unix_socket=False: None  # type: ignore[assignment]


@dataclass
class SimHandle:
    """Everything a test needs to drive the simulator."""

    server: TestServer
    model: GatewayModel
    faults: FaultConfig
    hub: WsHub

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.server.port}"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}"

    async def advance(self, seconds: float) -> list[dict[str, Any]]:
        return await self.model.advance_and_emit(seconds)

    def press_button(self) -> None:
        self.model.press_button()

    async def wait_until(self, predicate: Callable[[], bool], timeout: float = 5.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() > deadline:
                raise AssertionError("condition not met in time")
            await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def sim_config() -> SimConfig:
    """Fast physics for tests."""
    return SimConfig(full_travel_s=4.0, tilt_ms_default=100, tick_s=0.05, claim_timeout_s=2.0)


@pytest.fixture
def sim_model(sim_config: SimConfig) -> GatewayModel:
    model = GatewayModel.from_fixture(FIXTURES / "home.json", sim_config)
    model.tokens[TEST_TOKEN] = TEST_USER
    model.accounts[TEST_USER] = {"user": TEST_USER, "secret": TEST_TOKEN, "source": "admin"}
    assert model.info["sn"] == TEST_SN
    return model


async def _start_sim(model: GatewayModel, *, ticker: bool) -> SimHandle:
    faults = FaultConfig()
    app = create_app(model, faults=faults, ticker=ticker)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    return SimHandle(server=server, model=model, faults=faults, hub=app["hub"])


@pytest.fixture
async def simulator(sim_model: GatewayModel) -> AsyncIterator[SimHandle]:
    """Simulator whose clock only advances via ``advance()`` (deterministic)."""
    handle = await _start_sim(sim_model, ticker=False)
    try:
        yield handle
    finally:
        await handle.server.close()


@pytest.fixture
async def live_simulator(sim_model: GatewayModel) -> AsyncIterator[SimHandle]:
    """Simulator with a real-time ticker (for end-to-end HA tests)."""
    handle = await _start_sim(sim_model, ticker=True)
    try:
        yield handle
    finally:
        await handle.server.close()


@pytest.fixture
async def http_session() -> AsyncIterator[ClientSession]:
    async with ClientSession() as session:
        yield session


@pytest.fixture
def entry_options() -> dict[str, Any]:
    """Fast tilt timing for tests."""
    return {OPT_CLICK_MARGIN_MS: 50, OPT_FALLBACK_CLICK_PAUSE_MS: 200, OPT_TILT_SETTLE_MS: 100}


@pytest.fixture
def mock_config_entry(live_simulator: SimHandle, entry_options: dict[str, Any]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Zuhause",
        unique_id=TEST_SN,
        data={
            CONF_HOST: live_simulator.host,
            CONF_TOKEN: TEST_TOKEN,
            CONF_USERNAME: TEST_USER,
            CONF_SOURCE: "admin",
            CONF_SERIAL: TEST_SN,
        },
        options=entry_options,
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, live_simulator: SimHandle, mock_config_entry: MockConfigEntry
) -> AsyncIterator[MockConfigEntry]:
    """Set the entry up and tear it down again (stops the websocket task)."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    try:
        yield mock_config_entry
    finally:
        if mock_config_entry.state.recoverable:
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
            await hass.async_block_till_done()
