"""Constants of the Wiser by Feller integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "feller_wiser"
MANUFACTURER: Final = "Feller AG"

PLATFORMS: Final[list[Platform]] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.SWITCH,
]

# config entry data
CONF_TOKEN: Final = "token"  # noqa: S105 - config key, not a secret
CONF_USERNAME: Final = "username"
CONF_SOURCE: Final = "source"
CONF_SERIAL: Final = "serial"

# options
OPT_POLL_INTERVAL: Final = "poll_interval"
OPT_REGISTER_BUTTONS: Final = "register_buttons"
OPT_ROOMS_AS_AREAS: Final = "rooms_as_areas"
OPT_TILT_MODE: Final = "tilt_mode"
OPT_CLICK_MARGIN_MS: Final = "click_margin_ms"
OPT_FALLBACK_CLICK_PAUSE_MS: Final = "fallback_click_pause_ms"
OPT_TILT_SETTLE_MS: Final = "tilt_settle_ms"
OPT_TILT_MAX_ROUNDS: Final = "tilt_max_rounds"
OPT_TILT_FALLBACK_REFERENCE: Final = "tilt_fallback_reference"
OPT_READ_MOTOR_CONFIG: Final = "read_motor_config"

DEFAULT_POLL_INTERVAL: Final = 120
MIN_POLL_INTERVAL: Final = 30
MAX_POLL_INTERVAL: Final = 600
POLL_INTERVAL_WS_DOWN: Final = 30
DEFAULT_REGISTER_BUTTONS: Final = True
DEFAULT_ROOMS_AS_AREAS: Final = True
DEFAULT_TILT_MODE: Final = "auto"
DEFAULT_CLICK_MARGIN_MS: Final = 300
DEFAULT_FALLBACK_CLICK_PAUSE_MS: Final = 1500
DEFAULT_TILT_SETTLE_MS: Final = 1500
DEFAULT_TILT_MAX_ROUNDS: Final = 3
DEFAULT_TILT_FALLBACK_REFERENCE: Final = True
DEFAULT_READ_MOTOR_CONFIG: Final = True

TILT_MODES: Final = ["auto", "reference"]
STRUCTURE_REFRESH_INTERVAL_S: Final = 6 * 3600
DEVICE_DETAIL_PAUSE_S: Final = 0.5

# events / signals
EVENT_BUTTON: Final = f"{DOMAIN}_button"
EVENT_FINDME: Final = f"{DOMAIN}_findme"
SIGNAL_STRUCTURE_UPDATED: Final = f"{DOMAIN}_structure_updated_{{}}"
SIGNAL_BUTTON_EVENT: Final = f"{DOMAIN}_button_event_{{}}"

# services
SERVICE_SET_TILT_STEPS: Final = "set_tilt_steps"
SERVICE_SET_TARGET_STATE: Final = "set_target_state"
SERVICE_LOAD_CTRL: Final = "load_ctrl"
SERVICE_REFRESH_STRUCTURE: Final = "refresh_structure"

ATTR_LOAD_ID: Final = "load_id"
ATTR_LEVEL_RAW: Final = "level_raw"
ATTR_TILT_STEPS: Final = "tilt_steps"
ATTR_MOVING: Final = "moving"
ATTR_LEARNING: Final = "learning"
ATTR_LOCKED: Final = "locked"
ATTR_TILT_MS: Final = "tilt_ms"
ATTR_KIND: Final = "kind"
ATTR_TILT_SOURCE: Final = "tilt_source"

# repairs
ISSUE_SERIAL_MISMATCH: Final = "gateway_serial_mismatch"
ISSUE_FIRMWARE_TOO_OLD: Final = "firmware_too_old"
ISSUE_MOTOR_UNCALIBRATED: Final = "motor_uncalibrated"
ISSUE_BUTTONS_UNREGISTERED: Final = "buttons_unregistered"
ISSUE_DEVICE_DETAILS_FAILED: Final = "device_details_failed"

MIN_FIRMWARE_BUTTONS: Final = (6, 0, 41)
STORAGE_VERSION: Final = 1
STORAGE_KEY_DETAILS: Final = f"{DOMAIN}.device_details.{{}}"
