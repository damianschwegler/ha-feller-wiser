"""Cover entities and the tilt controller against the live simulator."""

import asyncio

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DOMAIN as COVER_DOMAIN,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
    SERVICE_STOP_COVER,
    CoverState,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import ATTR_TILT_STEPS, DOMAIN
from tests.conftest import SimHandle

BUERO = "cover.buro"
SONNENSTORE = "cover.sonnenstore"


async def _wait_state(hass: HomeAssistant, sim: SimHandle, entity_id: str, expected: str) -> None:
    await sim.wait_until(
        lambda: (
            hass.states.get(entity_id) is not None and hass.states.get(entity_id).state == expected
        )
    )


async def _wait_details(sim: SimHandle, entry: MockConfigEntry, key: str) -> None:
    await sim.wait_until(
        lambda: key in entry.runtime_data.coordinator.data.motor_configs, timeout=10
    )


async def test_entities_and_attributes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    covers = list(hass.states.async_all("cover"))
    assert len(covers) == 11
    state = hass.states.get(BUERO)
    assert state is not None, hass.states.async_entity_ids("cover")
    assert state.state == CoverState.CLOSED
    assert state.attributes[ATTR_CURRENT_POSITION] == 0
    assert state.attributes[ATTR_CURRENT_TILT_POSITION] == 44  # step 4
    assert state.attributes[ATTR_TILT_STEPS] == 4
    assert state.attributes["load_id"] == 64
    assert state.attributes["device_class"] == "blind"
    features = state.attributes[ATTR_SUPPORTED_FEATURES]
    assert features & 128  # SET_TILT_POSITION
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    await hass.async_block_till_done()
    state = hass.states.get(BUERO)
    assert state.attributes["tilt_ms"] == 300

    awning = hass.states.get(SONNENSTORE)
    assert awning is not None
    assert awning.attributes["device_class"] == "awning"
    assert ATTR_CURRENT_TILT_POSITION not in awning.attributes
    await _wait_details(live_simulator, setup_integration, "00001005_0")
    await hass.async_block_till_done()
    assert not hass.states.get(SONNENSTORE).attributes[ATTR_SUPPORTED_FEATURES] & 128


async def test_open_close_stop(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    motor = live_simulator.model.loads[64]
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_OPEN_COVER, {ATTR_ENTITY_ID: BUERO}, blocking=True
    )
    await _wait_state(hass, live_simulator, BUERO, CoverState.OPENING)
    await asyncio.sleep(0.5)
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_STOP_COVER, {ATTR_ENTITY_ID: BUERO}, blocking=True
    )
    await _wait_state(hass, live_simulator, BUERO, CoverState.OPEN)
    assert 0 < motor.level < 10000
    assert 0 < hass.states.get(BUERO).attributes[ATTR_CURRENT_POSITION] < 100
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_CLOSE_COVER, {ATTR_ENTITY_ID: BUERO}, blocking=True
    )
    await _wait_state(hass, live_simulator, BUERO, CoverState.CLOSING)
    await _wait_state(hass, live_simulator, BUERO, CoverState.CLOSED)
    assert motor.level == 10000


async def test_set_position(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    motor = live_simulator.model.loads[64]
    await hass.services.async_call(
        COVER_DOMAIN,
        SERVICE_SET_COVER_POSITION,
        {ATTR_ENTITY_ID: BUERO, ATTR_POSITION: 60},
        blocking=True,
    )
    await live_simulator.wait_until(
        lambda: motor.level == 4000 and motor.moving == "stop", timeout=10
    )
    await live_simulator.wait_until(
        lambda: hass.states.get(BUERO).attributes[ATTR_CURRENT_POSITION] == 60
    )


async def test_tilt_relative_clicks(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    motor = live_simulator.model.loads[64]
    assert motor.tilt == 4
    await hass.services.async_call(
        COVER_DOMAIN,
        SERVICE_SET_COVER_TILT_POSITION,
        {ATTR_ENTITY_ID: BUERO, ATTR_TILT_POSITION: 78},
        blocking=True,
    )
    assert motor.tilt == 7
    assert motor.clicks_received == 3
    assert ("up", "click") in motor.ctrl_log
    assert hass.states.get(BUERO).attributes[ATTR_TILT_STEPS] == 7
    assert hass.states.get(BUERO).attributes[ATTR_CURRENT_TILT_POSITION] == 78


async def test_tilt_lost_clicks_are_corrected(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    motor = live_simulator.model.loads[64]
    live_simulator.faults.drop_every_nth_click = 2
    response = await hass.services.async_call(
        DOMAIN,
        "set_tilt_steps",
        {ATTR_ENTITY_ID: BUERO, "steps": 8, "mode": "absolute"},
        blocking=True,
        return_response=True,
    )
    assert motor.tilt == 8
    outcome = response[BUERO]
    assert outcome["result"] == "ok"
    assert outcome["rounds"] >= 1
    assert outcome["tilt_steps"] == 8


async def test_tilt_to_zero_uses_reference_run(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    motor = live_simulator.model.loads[64]
    response = await hass.services.async_call(
        DOMAIN,
        "set_tilt_steps",
        {ATTR_ENTITY_ID: BUERO, "steps": 0},
        blocking=True,
        return_response=True,
    )
    assert response[BUERO]["result"] == "done_reference"
    assert motor.tilt == 0
    assert motor.clicks_received == 0


async def test_tilt_relative_mode_and_number_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    motor = live_simulator.model.loads[64]
    await hass.services.async_call(
        DOMAIN,
        "set_tilt_steps",
        {ATTR_ENTITY_ID: BUERO, "steps": -2, "mode": "relative"},
        blocking=True,
    )
    assert motor.tilt == 2
    number = hass.states.get("number.buro_tilt_step")
    assert number is not None
    assert float(number.state) == 2.0
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: number.entity_id, "value": 5}, blocking=True
    )
    assert motor.tilt == 5


async def test_tilt_skipped_while_moving(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await _wait_details(live_simulator, setup_integration, "00001001_0")
    motor = live_simulator.model.loads[64]
    # long travel, longer than the 10 s grace period is unrealistic for tests: shorten it
    from custom_components.feller_wiser import tilt_controller

    tilt_controller.MOVING_WAIT_BEFORE_START_S = 0.3
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_OPEN_COVER, {ATTR_ENTITY_ID: BUERO}, blocking=True
    )
    await live_simulator.wait_until(lambda: motor.moving == "up")
    response = await hass.services.async_call(
        DOMAIN,
        "set_tilt_steps",
        {ATTR_ENTITY_ID: BUERO, "steps": 6},
        blocking=True,
        return_response=True,
    )
    assert response[BUERO]["result"] == "skipped_moving"
    assert motor.clicks_received == 0
    tilt_controller.MOVING_WAIT_BEFORE_START_S = 10.0


async def test_locked_blind_refuses(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await live_simulator.model.set_load_state(64, {"flags": {"locked": 1}})
    await live_simulator.wait_until(lambda: hass.states.get(BUERO).attributes["locked"] is True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            COVER_DOMAIN, SERVICE_OPEN_COVER, {ATTR_ENTITY_ID: BUERO}, blocking=True
        )


async def test_raw_services(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    motor = live_simulator.model.loads[64]
    await hass.services.async_call(
        DOMAIN,
        "set_target_state",
        {ATTR_ENTITY_ID: BUERO, "level": 10000, "tilt": 6},
        blocking=True,
    )
    await live_simulator.wait_until(lambda: motor.tilt == 6 and motor.moving == "stop", timeout=10)
    await hass.services.async_call(
        DOMAIN,
        "load_ctrl",
        {ATTR_ENTITY_ID: BUERO, "button": "down", "event": "click"},
        blocking=True,
    )
    await live_simulator.wait_until(lambda: motor.tilt == 5, timeout=5)
    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN, "set_tilt_steps", {ATTR_ENTITY_ID: SONNENSTORE, "steps": 3}, blocking=True
        )


async def test_wall_switch_push_updates_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await live_simulator.wait_until(
        lambda: setup_integration.runtime_data.coordinator.data.ws_connected
    )
    await live_simulator.model.set_load_state(64, {"level": 0, "tilt": 0, "moving": "stop"})
    await _wait_state(hass, live_simulator, BUERO, CoverState.OPEN)
    assert hass.states.get(BUERO).attributes[ATTR_CURRENT_POSITION] == 100
