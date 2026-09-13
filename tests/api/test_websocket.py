"""Websocket client against the simulator."""

import asyncio

from aiohttp import ClientSession

from custom_components.feller_wiser.api import LoadEvent, SensorEvent, WiserWebSocket, WsEvent
from custom_components.feller_wiser.api.events import ButtonEvent
from tests.conftest import SimHandle
from tests.const import TEST_TOKEN


async def wait_for(predicate, timeout: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


async def test_connect_dump_and_push(simulator: SimHandle, http_session: ClientSession) -> None:
    events: list[WsEvent] = []
    connections: list[bool] = []
    ws = WiserWebSocket(
        f"ws://{simulator.host}/api",
        TEST_TOKEN,
        http_session,
        on_event=events.append,
        on_connection=connections.append,
    )
    await ws.async_start()
    try:
        await wait_for(lambda: len([e for e in events if isinstance(e, LoadEvent)]) >= 16)
        assert connections == [True]
        assert ws.connected
        ids = {e.id for e in events if isinstance(e, LoadEvent)}
        assert 64 in ids
        events.clear()
        await simulator.model.set_sensor_value(19, 22.5)
        await wait_for(lambda: any(isinstance(e, SensorEvent) for e in events))
        sensor = next(e for e in events if isinstance(e, SensorEvent))
        assert sensor.data == {"value": 22.5}
        await simulator.model.press_physical_button(101, "click", "scene")
        await wait_for(lambda: any(isinstance(e, ButtonEvent) for e in events))
        assert ws.stats.frames >= 2
    finally:
        await ws.async_stop()
    assert not ws.connected
    assert connections[-1] is False


async def test_reconnect_after_disconnect(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    connections: list[bool] = []
    ws = WiserWebSocket(
        f"ws://{simulator.host}/api",
        TEST_TOKEN,
        http_session,
        on_event=lambda _e: None,
        on_connection=connections.append,
    )
    await ws.async_start()
    try:
        await wait_for(lambda: connections == [True])
        await simulator.hub.disconnect_all()
        await wait_for(lambda: connections[-2:] == [False, True], timeout=5)
        assert ws.stats.connects == 2
    finally:
        await ws.async_stop()


async def test_bad_token_triggers_auth_failed(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    auth_failed = asyncio.Event()
    ws = WiserWebSocket(
        f"ws://{simulator.host}/api",
        "wrong",
        http_session,
        on_event=lambda _e: None,
        on_auth_failed=auth_failed.set,
    )
    await ws.async_start()
    try:
        await asyncio.wait_for(auth_failed.wait(), 3)
        assert not ws.connected
    finally:
        await ws.async_stop()


async def test_send_command_ctrl_loads(simulator: SimHandle, http_session: ClientSession) -> None:
    ws = WiserWebSocket(
        f"ws://{simulator.host}/api", TEST_TOKEN, http_session, on_event=lambda _e: None
    )
    await ws.async_start()
    try:
        await wait_for(lambda: ws.connected)
        await ws.send_command("ctrl_loads", id=64, button="up", event="click")
        await wait_for(lambda: simulator.model.loads[64].clicks_received == 1)
    finally:
        await ws.async_stop()
