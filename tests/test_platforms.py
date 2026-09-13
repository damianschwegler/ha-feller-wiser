"""Scene, sensor, binary sensor, climate, event, button platforms."""

from homeassistant.components.climate import ATTR_TEMPERATURE, HVACAction
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import DOMAIN, EVENT_BUTTON
from tests.conftest import SimHandle


async def test_scene(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    scenes = hass.states.async_entity_ids("scene")
    assert len(scenes) == 2
    alles_zu = next(s for s in hass.states.async_all("scene") if s.attributes.get("scene_id") == 40)
    assert alles_zu.attributes["job_id"] == 50
    await hass.services.async_call(
        "scene", "turn_on", {ATTR_ENTITY_ID: alles_zu.entity_id}, blocking=True
    )
    assert live_simulator.model.jobs_run == [50]


async def test_sensors(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    temp = hass.states.get("sensor.temperatur_wohnzimmer")
    assert temp is not None
    assert float(temp.state) == 21.5
    assert temp.attributes["unit_of_measurement"] == "°C"
    wind = hass.states.get("sensor.wind")
    assert float(wind.state) == 9.0  # HA converts 2.5 m/s to km/h
    regen = hass.states.get("binary_sensor.regen")
    assert regen.state == STATE_OFF
    await live_simulator.wait_until(
        lambda: setup_integration.runtime_data.coordinator.data.ws_connected
    )
    await live_simulator.model.set_sensor_value(19, 22.0)
    await live_simulator.wait_until(
        lambda: float(hass.states.get("sensor.temperatur_wohnzimmer").state) == 22.0
    )
    await live_simulator.model.set_sensor_value(25, 1)
    await live_simulator.wait_until(
        lambda: hass.states.get("binary_sensor.regen").state == STATE_ON
    )
    # weather station device exists with the sensors attached
    dev_reg = dr.async_get(hass)
    station = dev_reg.async_get_device_by_identifier(
        (DOMAIN, "00004001"), setup_integration.entry_id
    )
    assert station is not None
    assert station.model == "Wetterstation"


async def test_gateway_diagnostics_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    ws = hass.states.get("binary_sensor.zuhause_push_connection")
    assert ws is not None
    await live_simulator.wait_until(
        lambda: hass.states.get("binary_sensor.zuhause_push_connection").state == STATE_ON
    )
    ent_reg = er.async_get(hass)
    rssi = ent_reg.async_get_entity_id("sensor", DOMAIN, "00429931_rssi")
    assert rssi is not None
    assert ent_reg.async_get(rssi).disabled  # diagnostic sensors are off by default
    problem = hass.states.get("binary_sensor.buro_problem")
    assert problem is not None and problem.state == STATE_OFF
    await live_simulator.model.set_load_state(64, {"flags": {"over_current": 1}})
    await live_simulator.wait_until(
        lambda: hass.states.get("binary_sensor.buro_problem").state == STATE_ON
    )


async def test_climate(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    climate = hass.states.get("climate.zuhause_wohnzimmer_heizung")
    assert climate is not None, hass.states.async_entity_ids("climate")
    assert climate.attributes["current_temperature"] == 21.5
    assert climate.attributes["temperature"] == 22.0
    assert climate.attributes["hvac_action"] == HVACAction.HEATING
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: climate.entity_id, ATTR_TEMPERATURE: 23.5},
        blocking=True,
    )
    assert live_simulator.model.hvac_states[79]["target_temperature"] == 23.5
    assert hass.states.get(climate.entity_id).attributes["temperature"] == 23.5


async def test_button_events(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await live_simulator.wait_until(
        lambda: setup_integration.runtime_data.coordinator.data.ws_connected
    )
    # sleeping buttons were registered at setup
    assert all(b.get("id") is not None for b in live_simulator.model.buttons)
    events: list[Event] = []
    hass.bus.async_listen(EVENT_BUTTON, events.append)
    await live_simulator.model.press_physical_button(101, "press", "scene")
    await live_simulator.wait_until(lambda: len(events) == 1)
    assert events[0].data["type"] == "press"
    assert events[0].data["channel"] == 0
    assert events[0].data["wiser_device"] == "00003001"
    assert events[0].data["device_id"] is not None
    event_entities = [
        s for s in hass.states.async_all("event") if s.attributes.get("button_id") == 101
    ]
    assert len(event_entities) == 1
    await live_simulator.wait_until(
        lambda: hass.states.get(event_entities[0].entity_id).attributes.get("event_type") == "press"
    )


async def test_device_triggers(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    from homeassistant.components.device_automation import (
        DeviceAutomationType,
        async_get_device_automations,
    )

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, "00003001"), setup_integration.entry_id
    )
    assert device is not None
    result = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, [device.id])
    ours = [t for t in result[device.id] if t["domain"] == DOMAIN]
    assert {t["subtype"] for t in ours} >= {"button_1", "button_2"}
    assert {t["type"] for t in ours} == {"click", "press", "release"}


async def test_identify_and_gateway_buttons(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.buro_identify"}, blocking=True
    )
    assert live_simulator.model.pings == [64]
    refresh = next(
        s for s in hass.states.async_all("button") if s.entity_id.endswith("reload_structure")
    )
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: refresh.entity_id}, blocking=True
    )
    assert setup_integration.runtime_data.coordinator.data.structure_version >= 2


async def test_new_load_appears_after_refresh(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    from simulator.motor import MotorLoad

    model = live_simulator.model
    model.loads[99] = MotorLoad(
        id=99, name="Neue Store", type="motor", device="00001007", channel=1, room=6, kind=1
    )
    await hass.services.async_call(DOMAIN, "refresh_structure", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("cover.neue_store") is not None
