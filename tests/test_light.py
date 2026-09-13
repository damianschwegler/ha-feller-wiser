"""Light and switch entities."""

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGBW_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feller_wiser.const import DOMAIN
from tests.conftest import SimHandle

BUEROLAMPE = "light.burolampe"
STEHLAMPE = "light.stehlampe"
DECKENLICHT = "light.deckenlicht"
LEDBAND = "light.led_band"
STECKDOSE = "switch.steckdose_gang"


async def test_light_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    assert hass.states.get(BUEROLAMPE).state == STATE_OFF
    assert hass.states.get(BUEROLAMPE).attributes["load_id"] == 20
    stehlampe = hass.states.get(STEHLAMPE)
    assert stehlampe.state == STATE_ON
    assert stehlampe.attributes[ATTR_BRIGHTNESS] == 128
    assert stehlampe.attributes[ATTR_COLOR_MODE] == "brightness"
    decke = hass.states.get(DECKENLICHT)
    assert decke.attributes[ATTR_COLOR_TEMP_KELVIN] == 3000
    led = hass.states.get(LEDBAND)
    assert led.attributes[ATTR_RGBW_COLOR] == (255, 128, 0, 0)
    assert hass.states.get(STECKDOSE).state == STATE_ON
    assert "light.steckdose_gang" not in hass.states.async_entity_ids()


async def test_turn_on_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    model = live_simulator.model
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: BUEROLAMPE}, blocking=True
    )
    assert model.loads[20].bri == 10000
    await live_simulator.wait_until(lambda: hass.states.get(BUEROLAMPE).state == STATE_ON)
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: STEHLAMPE, ATTR_BRIGHTNESS: 51},
        blocking=True,
    )
    assert model.loads[21].bri == 2000
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: DECKENLICHT, ATTR_COLOR_TEMP_KELVIN: 4000},
        blocking=True,
    )
    assert model.loads[22].ct == 4000
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: LEDBAND, ATTR_RGBW_COLOR: (1, 2, 3, 4)},
        blocking=True,
    )
    assert (model.loads[23].red, model.loads[23].white) == (1, 4)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: STEHLAMPE}, blocking=True
    )
    assert model.loads[21].bri == 0
    await live_simulator.wait_until(lambda: hass.states.get(STEHLAMPE).state == STATE_OFF)


async def test_switch_and_flags(
    hass: HomeAssistant, setup_integration: MockConfigEntry, live_simulator: SimHandle
) -> None:
    model = live_simulator.model
    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: STECKDOSE}, blocking=True
    )
    assert model.loads[24].bri == 0
    await live_simulator.wait_until(lambda: hass.states.get(STECKDOSE).state == STATE_OFF)
    flag = next(
        s for s in hass.states.async_all("switch") if s.attributes.get("symbol") == "absent"
    )
    assert flag.state == STATE_OFF
    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: flag.entity_id}, blocking=True
    )
    assert model.flags[39]["value"] is True
    assert hass.states.get(flag.entity_id).state == STATE_ON
    # raw ctrl works on lights too
    await hass.services.async_call(
        DOMAIN,
        "load_ctrl",
        {ATTR_ENTITY_ID: BUEROLAMPE, "button": "toggle", "event": "click"},
        blocking=True,
    )
    assert model.loads[20].bri == 10000
