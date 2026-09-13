"""Constants and enums for the Wiser by Feller µGateway API."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DEFAULT_REQUEST_TIMEOUT: Final = 10.0
"""Seconds for an ordinary REST request."""

CLAIM_TIMEOUT: Final = 40.0
"""Seconds to wait for the claim request (gateway blocks up to 30 s for the button press)."""

DEVICE_DETAIL_TIMEOUT: Final = 30.0
"""Seconds for /api/devices/{id} which can be slow on the first call."""

WS_IDLE_TIMEOUT: Final = 900.0
"""Seconds without any websocket frame before the connection is considered dead."""

WS_HEARTBEAT: Final = 30.0
"""Protocol-level ping interval on the websocket."""

DEFAULT_API_USER: Final = "homeassistant"
"""Account name we claim on the gateway. Re-claiming the same name replaces the token."""

CLAIM_SOURCES: Final[tuple[str | None, ...]] = ("admin", "installer", None)
"""Accounts to copy rooms/names from, in order of preference. `None` = plain claim."""

LEVEL_MAX: Final = 10000
BRI_MAX: Final = 10000
TILT_MAX: Final = 9
CT_MIN: Final = 1000
CT_MAX: Final = 20000

MSG_API_LOCKED: Final = "api is locked"
MSG_UNAUTHORIZED: Final = "unauthorized user"
MSG_SOURCE_NOT_FOUND: Final = "not a directory"
MSG_NO_SITE_INFO: Final = "no site info"


class LoadType(StrEnum):
    """Main type of a load (`type` field)."""

    ONOFF = "onoff"
    DIM = "dim"
    MOTOR = "motor"
    DALI = "dali"
    HVAC = "hvac"
    UNKNOWN = "unknown"


class LoadSubType(StrEnum):
    """Sub type of a load (`sub_type` field)."""

    NONE = ""
    DTO = "dto"
    TW = "tw"
    RGB = "rgb"
    RELAY = "relay"
    UNKNOWN = "unknown"


class LightKind:
    """`kind` values of light loads (app hint, may be missing)."""

    LIGHT: Final = 0
    SWITCH: Final = 1


class MotorKind:
    """`kind` values of motor loads (app hint, may be missing)."""

    MOTOR: Final = 0
    VENETIAN_BLINDS: Final = 1
    ROLLER_SHUTTERS: Final = 2
    AWNINGS: Final = 3


class Moving(StrEnum):
    """`moving` field of a motor state."""

    UP = "up"
    DOWN = "down"
    STOP = "stop"


class CtrlButton(StrEnum):
    """`button` values for /api/loads/{id}/ctrl."""

    ON = "on"
    OFF = "off"
    UP = "up"
    DOWN = "down"
    TOGGLE = "toggle"
    STOP = "stop"


class CtrlEvent(StrEnum):
    """`event` values for /api/loads/{id}/ctrl."""

    CLICK = "click"
    PRESS = "press"
    RELEASE = "release"


class SensorType(StrEnum):
    """`type` of a sensor object."""

    TEMPERATURE = "temperature"
    ILLUMINANCE = "illuminance"
    BRIGHTNESS = "brightness"
    WIND = "wind"
    RAIN = "rain"
    HAIL = "hail"
    HUMIDITY = "humidity"
    CO2 = "CO2"
    WINDOW = "window"
    UNKNOWN = "unknown"


class ButtonEventType(StrEnum):
    """`cmd.event` of a websocket button frame."""

    CLICK = "click"
    PRESS = "press"
    RELEASE = "release"
