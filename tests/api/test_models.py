"""Model parsing."""

import pytest

from custom_components.feller_wiser.api import (
    Device,
    Load,
    LoadState,
    LoadSubType,
    LoadType,
    Moving,
    Sensor,
    SensorType,
    parse_ws_frame,
)
from custom_components.feller_wiser.api.errors import (
    ApiLockedError,
    NotAWiserGatewayError,
    RequestFailedError,
    SourceNotFoundError,
    UnauthorizedError,
)
from custom_components.feller_wiser.api.events import (
    ButtonEvent,
    FindMeEvent,
    LoadEvent,
    SensorEvent,
    UnknownEvent,
)
from custom_components.feller_wiser.api.jsend import unwrap


def test_load_parsing_tolerates_unknown_types() -> None:
    load = Load.from_api(
        {"id": 5, "type": "weird", "sub_type": "x", "device": "0000abcd", "channel": 1}
    )
    assert load.type is LoadType.UNKNOWN
    assert load.sub_type is LoadSubType.UNKNOWN
    assert load.raw_type == "weird"
    assert load.unique_key == "0000abcd_1"
    assert load.room is None


def test_motor_state_merge() -> None:
    state = LoadState.from_api(
        {"level": 8160, "tilt": 0, "moving": "stop", "flags": {"moving": 0, "locked": 0}}
    )
    assert state.moving is Moving.STOP
    merged = state.merge({"moving": "up", "flags": {"moving": 1}})
    assert merged.moving is Moving.UP
    assert merged.level == 8160
    assert merged.flags.moving is True
    assert merged.flags.locked is False
    assert merged.is_moving


def test_dim_state() -> None:
    state = LoadState.from_api({"bri": 5000, "flags": {"over_temperature": 1}})
    assert state.bri == 5000
    assert state.flags.over_temperature
    assert state.flags.has_problem


def test_device_details() -> None:
    basic = Device.from_api(
        {"id": "00001001", "last_seen": 3, "a": {"comm_name": "Storenschalter 1K"}}
    )
    assert not basic.has_details
    assert basic.model == "Storenschalter 1K"
    detailed = Device.from_api(
        {
            "id": "00001001",
            "outputs": [{"load": 64, "type": "motor", "sub_type": ""}],
            "inputs": [{"type": "up down"}],
        }
    )
    merged = basic.with_details(detailed)
    assert merged.has_details
    assert merged.outputs[0].load == 64
    assert merged.a is not None


def test_sensor_parsing() -> None:
    sensor = Sensor.from_api(
        {
            "id": 19,
            "name": "T",
            "unit": "℃",
            "value": 19.9,
            "device": "0000a98f",
            "channel": 0,
            "type": "temperature",
        }
    )
    assert sensor.type is SensorType.TEMPERATURE
    assert sensor.numeric_value == 19.9
    assert sensor.with_value(20.5).numeric_value == 20.5


def test_unwrap_maps_errors() -> None:
    assert unwrap({"status": "success", "data": [1]}, "x") == [1]
    with pytest.raises(ApiLockedError):
        unwrap({"status": "error", "message": "api is locked, log in"}, "x")
    with pytest.raises(UnauthorizedError):
        unwrap({"status": "error", "message": "unauthorized user"}, "x")
    with pytest.raises(SourceNotFoundError):
        unwrap({"status": "error", "message": "/flash/accounts/foo is not a directory"}, "x")
    with pytest.raises(RequestFailedError):
        unwrap({"status": "error", "message": "something else"}, "x")
    with pytest.raises(NotAWiserGatewayError):
        unwrap({"foo": "bar"}, "x")


def test_parse_ws_frames() -> None:
    event = parse_ws_frame({"load": {"id": 3, "state": {"moving": "stop", "tilt": 0}}})
    assert isinstance(event, LoadEvent)
    assert event.id == 3
    assert event.state == {"moving": "stop", "tilt": 0}
    sensor = parse_ws_frame({"sensor": {"id": 19, "value": 20.1}})
    assert isinstance(sensor, SensorEvent)
    assert sensor.data == {"value": 20.1}
    button = parse_ws_frame({"button": {"id": 101, "cmd": {"event": "click", "type": "scene"}}})
    assert isinstance(button, ButtonEvent)
    assert button.event == "click"
    findme = parse_ws_frame({"findme": {"load": 345}})
    assert isinstance(findme, FindMeEvent)
    assert findme.target == {"load": 345}
    unknown = parse_ws_frame({"something": 1})
    assert isinstance(unknown, UnknownEvent)
    assert unknown.key == "something"
    assert parse_ws_frame({}) is None
