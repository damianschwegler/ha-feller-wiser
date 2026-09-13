"""REST client against the simulator."""

import asyncio

from aiohttp import ClientSession
import pytest

from custom_components.feller_wiser.api import (
    ApiLockedError,
    ClaimTimeoutError,
    CtrlButton,
    CtrlEvent,
    LoadType,
    Moving,
    NotAWiserGatewayError,
    SourceNotFoundError,
    UnauthorizedError,
    WiserClient,
    WiserConnectionError,
    claim_with_source_detection,
    normalize_host,
)
from tests.conftest import SimHandle
from tests.const import TEST_SN, TEST_TOKEN


def test_normalize_host() -> None:
    assert normalize_host(" http://wiser-1.local/ ") == "wiser-1.local"
    assert normalize_host("192.168.1.5:8080/api") == "192.168.1.5:8080"


async def test_info_and_site_without_token(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    client = WiserClient(simulator.host, http_session)
    info = await client.get_info()
    assert info.sn == TEST_SN
    assert info.api == "2.0"
    site = await client.get_site()
    assert site.name == "Zuhause"


async def test_locked_without_token(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session)
    with pytest.raises(ApiLockedError):
        await client.get_loads()


async def test_unauthorized_with_wrong_token(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    client = WiserClient(simulator.host, http_session, token="nope")
    with pytest.raises(UnauthorizedError):
        await client.get_loads()


async def test_not_a_gateway(http_session: ClientSession, unused_tcp_port: int) -> None:
    client = WiserClient(f"127.0.0.1:{unused_tcp_port}", http_session, request_timeout=1)
    with pytest.raises(WiserConnectionError):
        await client.get_info()


async def test_claim_with_button_press(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session)
    task = asyncio.create_task(client.claim("hatest", "admin"))
    await asyncio.sleep(0.1)
    assert simulator.model.claim.active
    simulator.press_button()
    account = await task
    assert account.user == "hatest"
    assert account.secret
    assert client.token == account.secret
    me = await client.get_account()
    assert me.user == "hatest"
    assert me.source == "admin"


async def test_claim_timeout(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session)
    with pytest.raises(ClaimTimeoutError):
        await client.claim("hatest")


async def test_claim_unknown_source(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session)
    with pytest.raises(SourceNotFoundError):
        await client.claim("hatest", "nobody")


async def test_claim_source_detection_falls_back(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    del simulator.model.accounts["admin"]
    client = WiserClient(simulator.host, http_session)
    attempts: list[str | None] = []
    simulator.model.config.auto_press_after_s = 0.05
    result = await claim_with_source_detection(client, "hatest", on_attempt=attempts.append)
    assert attempts == ["admin", "installer"]
    assert result.source == "installer"
    assert result.secret


async def test_structure_and_state(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session, token=TEST_TOKEN)
    loads = await client.get_loads()
    assert {load.id for load in loads} >= {1, 2, 3, 6, 7, 14, 15, 64, 81, 82, 83}
    buero = next(load for load in loads if load.id == 64)
    assert buero.type is LoadType.MOTOR
    assert buero.name == "Büro"
    assert buero.room == 1
    rooms = await client.get_rooms()
    assert {room.id: room.name for room in rooms}[1] == "Büro"
    devices = await client.get_devices()
    assert all(not d.has_details for d in devices)
    detail = await client.get_device("00001001")
    assert detail.outputs and detail.outputs[0].load == 64
    states = await client.get_load_states()
    assert states[64].level == 10000
    assert states[64].tilt == 4
    assert states[64].moving is Moving.STOP
    single = await client.get_load_state(64)
    assert single.tilt == 4
    sensors = await client.get_sensors()
    assert len(sensors) == 5
    buttons = await client.get_buttons()
    assert any(b.id is None for b in buttons)
    hvac = await client.get_hvac_groups()
    assert hvac[0].id == 79
    hvac_states = await client.get_hvac_states()
    assert hvac_states[79].target_temperature == 22.0
    flags = await client.get_flags()
    assert flags[0].symbol == "absent"
    health = await client.get_health()
    assert health.mem_free == 80688
    net = await client.get_net_state()
    assert net.hostname == "wiser-00429931"
    assert await client.get_rssi() == -58
    scenes = await client.get_scenes()
    assert scenes[0].job == 50


async def test_device_config_is_discarded(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    client = WiserClient(simulator.host, http_session, token=TEST_TOKEN)
    config = await client.read_device_config("00001001")
    motor = config.motor_output(0)
    assert motor is not None
    assert motor.tilt_ms == 300
    assert motor.tiltable is True
    assert simulator.model.open_configs == {}


async def test_control(simulator: SimHandle, http_session: ClientSession) -> None:
    client = WiserClient(simulator.host, http_session, token=TEST_TOKEN)
    result = await client.set_target_state(64, level=0)
    assert result["target_state"] == {"level": 0}
    assert simulator.model.loads[64].moving == "up"
    await client.ctrl(64, CtrlButton.STOP, CtrlEvent.CLICK)
    assert simulator.model.loads[64].moving == "stop"
    await client.ctrl(64, "up", "click")
    await simulator.advance(0.5)
    assert simulator.model.loads[64].tilt == 5
    await client.ping_load(64)
    assert simulator.model.pings == [64]
    await client.run_job(50)
    assert simulator.model.jobs_run == [50]
    flag = await client.set_flag(39, True)
    assert flag.value is True
    await client.set_hvac_target(79, 23.5)
    assert simulator.model.hvac_states[79]["target_temperature"] == 23.5
    button = await client.register_button("00003001", 1)
    assert button.id is not None


async def test_requests_are_serialised(simulator: SimHandle, http_session: ClientSession) -> None:
    simulator.faults.latency_ms = 50
    client = WiserClient(simulator.host, http_session, token=TEST_TOKEN)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(client.get_loads(), client.get_rooms(), client.get_scenes())
    assert loop.time() - started >= 0.15


async def test_gateway_down_is_connection_error(
    simulator: SimHandle, http_session: ClientSession
) -> None:
    simulator.faults.reject_api = True
    client = WiserClient(simulator.host, http_session, token=TEST_TOKEN)
    with pytest.raises(WiserConnectionError):
        await client.get_loads()


async def test_non_json_is_not_a_gateway(http_session: ClientSession, simulator: SimHandle) -> None:
    client = WiserClient(simulator.host, http_session)
    with pytest.raises(NotAWiserGatewayError):
        await client._request("GET", "../sim/does-not-exist")
