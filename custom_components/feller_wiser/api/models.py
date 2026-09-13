"""Typed models for the µGateway REST API.

All parsers are tolerant: unknown keys are ignored, missing keys fall back to ``None`` or a
sane default, so a firmware update never breaks the integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Self

from .const import LoadSubType, LoadType, MotorKind, Moving, SensorType


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except TypeError, ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except TypeError, ValueError:
        return None


def _str(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _bool(value: Any) -> bool:
    return bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "on")


@dataclass(frozen=True, slots=True)
class Info:
    """`GET /api/info` (token-free)."""

    product: str
    instance_id: str
    sn: str
    api: str
    sw: str
    boot: str
    hw: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            product=_str(raw.get("product")),
            instance_id=_str(raw.get("instance_id")),
            sn=_str(raw.get("sn")),
            api=_str(raw.get("api")),
            sw=_str(raw.get("sw")),
            boot=_str(raw.get("boot")),
            hw=_str(raw.get("hw")),
        )


@dataclass(frozen=True, slots=True)
class Site:
    """`GET /api/site` (token-free, free-form)."""

    name: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self:
        """Parse the raw dict."""
        raw = raw or {}
        return cls(name=_str(raw.get("name")), raw=dict(raw))


@dataclass(frozen=True, slots=True)
class Account:
    """`GET /api/account` / claim / clone result."""

    user: str
    secret: str | None
    source: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            user=_str(raw.get("user")),
            secret=raw.get("secret"),
            source=raw.get("source"),
        )


@dataclass(frozen=True, slots=True)
class NetState:
    """`GET /api/net/state`."""

    hostname: str
    ip: str
    mac_addr: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            hostname=_str(raw.get("hostname")),
            ip=_str(raw.get("ip")),
            mac_addr=_str(raw.get("mac_addr")),
        )


@dataclass(frozen=True, slots=True)
class Health:
    """`GET /api/system/health`."""

    uptime: int | None
    mem_free: int | None
    mem_size: int | None
    flash_free: int | None
    sockets: int | None
    wlan_rssi: int | None
    wlan_resets: int | None
    max_tasks: int | None
    reboot_cause: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            uptime=_int_or_none(raw.get("uptime")),
            mem_free=_int_or_none(raw.get("mem_free")),
            mem_size=_int_or_none(raw.get("mem_size")),
            flash_free=_int_or_none(raw.get("flash_free")),
            sockets=_int_or_none(raw.get("sockets")),
            wlan_rssi=_int_or_none(raw.get("wlan_rssi")),
            wlan_resets=_int_or_none(raw.get("wlan_resets")),
            max_tasks=_int_or_none(raw.get("max_tasks")),
            reboot_cause=_str(raw.get("reboot_cause")),
        )


@dataclass(frozen=True, slots=True)
class Load:
    """`GET /api/loads` item. A load is an output channel, not a physical device."""

    id: int
    name: str
    type: LoadType
    sub_type: LoadSubType
    device: str
    channel: int
    unused: bool
    room: int | None
    kind: int | None
    raw_type: str
    raw_sub_type: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        raw_type = _str(raw.get("type"))
        raw_sub_type = _str(raw.get("sub_type"))
        try:
            load_type = LoadType(raw_type)
        except ValueError:
            load_type = LoadType.UNKNOWN
        try:
            sub_type = LoadSubType(raw_sub_type)
        except ValueError:
            sub_type = LoadSubType.UNKNOWN
        return cls(
            id=int(raw["id"]),
            name=_str(raw.get("name")),
            type=load_type,
            sub_type=sub_type,
            device=_str(raw.get("device")),
            channel=int(raw.get("channel", 0)),
            unused=_bool(raw.get("unused", False)),
            room=_int_or_none(raw.get("room")),
            kind=_int_or_none(raw.get("kind")),
            raw_type=raw_type,
            raw_sub_type=raw_sub_type,
        )

    @property
    def unique_key(self) -> str:
        """Stable key based on the physical device and its channel."""
        return f"{self.device}_{self.channel}"

    @property
    def is_motor(self) -> bool:
        """True for blinds/shutters/awnings."""
        return self.type is LoadType.MOTOR


@dataclass(frozen=True, slots=True)
class LoadFlags:
    """`state.flags` of any load; unknown keys kept in ``extra``."""

    direction: int | None = None
    learning: bool = False
    moving: bool = False
    under_current: bool = False
    over_current: bool = False
    over_temperature: bool = False
    timeout: bool = False
    locked: bool = False
    fading: bool = False
    noise: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self:
        """Parse the raw dict."""
        raw = dict(raw or {})
        known = {
            "direction": _int_or_none(raw.pop("direction", None)),
            "learning": _bool(raw.pop("learning", 0)),
            "moving": _bool(raw.pop("moving", 0)),
            "under_current": _bool(raw.pop("under_current", 0)),
            "over_current": _bool(raw.pop("over_current", 0)),
            "over_temperature": _bool(raw.pop("over_temperature", 0)),
            "timeout": _bool(raw.pop("timeout", 0)),
            "locked": _bool(raw.pop("locked", 0)),
            "fading": _bool(raw.pop("fading", 0)),
            "noise": _bool(raw.pop("noise", 0)),
        }
        return cls(**known, extra=raw)  # type: ignore[arg-type]

    def merge(self, raw: dict[str, Any] | None) -> LoadFlags:
        """Apply a partial flags dict on top of this one."""
        if not raw:
            return self
        merged = {**self.as_dict(), **raw}
        return LoadFlags.from_api(merged)

    def as_dict(self) -> dict[str, Any]:
        """Return the flags as the gateway would send them."""
        out: dict[str, Any] = {
            "direction": self.direction,
            "learning": int(self.learning),
            "moving": int(self.moving),
            "under_current": int(self.under_current),
            "over_current": int(self.over_current),
            "over_temperature": int(self.over_temperature),
            "timeout": int(self.timeout),
            "locked": int(self.locked),
            "fading": int(self.fading),
            "noise": int(self.noise),
        }
        out.update(self.extra)
        return out

    @property
    def has_problem(self) -> bool:
        """True if any fault flag is set."""
        return (
            self.under_current
            or self.over_current
            or self.over_temperature
            or self.timeout
            or self.noise
        )


@dataclass(frozen=True, slots=True)
class LoadState:
    """State of a load; one class for all types, unused fields stay ``None``."""

    bri: int | None = None
    ct: int | None = None
    red: int | None = None
    green: int | None = None
    blue: int | None = None
    white: int | None = None
    level: int | None = None
    tilt: int | None = None
    moving: Moving | None = None
    flags: LoadFlags = field(default_factory=LoadFlags)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self:
        """Parse a full state dict."""
        raw = raw or {}
        moving_raw = raw.get("moving")
        moving: Moving | None
        try:
            moving = None if moving_raw is None else Moving(str(moving_raw))
        except ValueError:
            moving = Moving.STOP
        return cls(
            bri=_int_or_none(raw.get("bri")),
            ct=_int_or_none(raw.get("ct")),
            red=_int_or_none(raw.get("red")),
            green=_int_or_none(raw.get("green")),
            blue=_int_or_none(raw.get("blue")),
            white=_int_or_none(raw.get("white")),
            level=_int_or_none(raw.get("level")),
            tilt=_int_or_none(raw.get("tilt")),
            moving=moving,
            flags=LoadFlags.from_api(raw.get("flags")),
            raw=dict(raw),
        )

    def merge(self, partial: dict[str, Any] | None) -> LoadState:
        """Apply a partial state (websocket frame) on top of this one."""
        if not partial:
            return self
        merged_raw = {**self.raw, **partial}
        if "flags" in partial:
            merged_raw["flags"] = self.flags.merge(partial.get("flags")).as_dict()
        return LoadState.from_api(merged_raw)

    @property
    def is_moving(self) -> bool:
        """True while a motor is running."""
        return self.moving is not None and self.moving is not Moving.STOP


@dataclass(frozen=True, slots=True)
class DeviceBlock:
    """A- or C-block of a device (actuator / control front)."""

    fw_id: str
    hw_id: str
    fw_version: str
    comm_ref: str
    comm_name: str
    serial_nr: str
    address: str
    cmd_matrix: str
    nubes_id: str

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self | None:
        """Parse the raw dict, ``None`` if the block is absent."""
        if not raw:
            return None
        return cls(
            fw_id=_str(raw.get("fw_id")),
            hw_id=_str(raw.get("hw_id")),
            fw_version=_str(raw.get("fw_version")),
            comm_ref=_str(raw.get("comm_ref")),
            comm_name=_str(raw.get("comm_name")),
            serial_nr=_str(raw.get("serial_nr")),
            address=_str(raw.get("address")),
            cmd_matrix=_str(raw.get("cmd_matrix")),
            nubes_id=_str(raw.get("nubes_id")),
        )


@dataclass(frozen=True, slots=True)
class DeviceInput:
    """Input channel (button) of a device."""

    type: str


@dataclass(frozen=True, slots=True)
class DeviceOutput:
    """Output channel of a device; ``load`` is the load id driven by this channel."""

    load: int | None
    type: str
    sub_type: str


@dataclass(frozen=True, slots=True)
class Device:
    """`GET /api/devices` item, optionally with details from `GET /api/devices/{id}`."""

    id: str
    last_seen: int | None
    a: DeviceBlock | None
    c: DeviceBlock | None
    inputs: tuple[DeviceInput, ...] | None = None
    outputs: tuple[DeviceOutput, ...] | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        inputs_raw = raw.get("inputs")
        outputs_raw = raw.get("outputs")
        return cls(
            id=_str(raw.get("id")),
            last_seen=_int_or_none(raw.get("last_seen")),
            a=DeviceBlock.from_api(raw.get("a")),
            c=DeviceBlock.from_api(raw.get("c")),
            inputs=(
                None
                if inputs_raw is None
                else tuple(DeviceInput(type=_str(i.get("type"))) for i in inputs_raw)
            ),
            outputs=(
                None
                if outputs_raw is None
                else tuple(
                    DeviceOutput(
                        load=_int_or_none(o.get("load")),
                        type=_str(o.get("type")),
                        sub_type=_str(o.get("sub_type")),
                    )
                    for o in outputs_raw
                )
            ),
        )

    def with_details(self, detailed: Device) -> Device:
        """Return a copy that carries the inputs/outputs of ``detailed``."""
        return replace(self, inputs=detailed.inputs, outputs=detailed.outputs)

    @property
    def has_details(self) -> bool:
        """True once inputs/outputs were fetched."""
        return self.inputs is not None or self.outputs is not None

    @property
    def model(self) -> str:
        """Human readable model name (control front first, actuator as fallback)."""
        if self.c and self.c.comm_name:
            return self.c.comm_name
        if self.a and self.a.comm_name:
            return self.a.comm_name
        return "Wiser device"

    @property
    def fw_version(self) -> str:
        """Actuator firmware version (used as cache key for device details)."""
        return self.a.fw_version if self.a else ""


@dataclass(frozen=True, slots=True)
class MotorOutputConfig:
    """Motor part of `outputs[channel]` in a device config object."""

    tilt_ms: int | None
    tiltable: bool | None
    relay_mode: bool | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self:
        """Parse the raw dict."""
        raw = raw or {}
        tiltable = raw.get("tiltable")
        relay = raw.get("relay_mode")
        return cls(
            tilt_ms=_int_or_none(raw.get("tilt_ms")),
            tiltable=None if tiltable is None else _bool(tiltable),
            relay_mode=None if relay is None else _bool(relay),
            raw=dict(raw),
        )


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """`GET /api/devices/{id}/config` (device is in config mode until DELETE)."""

    id: int
    outputs: tuple[dict[str, Any], ...]
    inputs: tuple[dict[str, Any], ...]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            outputs=tuple(raw.get("outputs") or ()),
            inputs=tuple(raw.get("inputs") or ()),
            raw=dict(raw),
        )

    def motor_output(self, channel: int) -> MotorOutputConfig | None:
        """Motor config of an output channel, ``None`` if not a motor."""
        if channel >= len(self.outputs):
            return None
        out = self.outputs[channel]
        if _str(out.get("type")) != "motor":
            return None
        return MotorOutputConfig.from_api(out)


@dataclass(frozen=True, slots=True)
class Room:
    """`GET /api/rooms` item (per-account)."""

    id: int
    name: str
    kind: int | None
    load_order: tuple[int, ...]

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            name=_str(raw.get("name")),
            kind=_int_or_none(raw.get("kind")),
            load_order=tuple(int(x) for x in raw.get("load_order") or ()),
        )


@dataclass(frozen=True, slots=True)
class Scene:
    """`GET /api/scenes` item; the load states live in the linked job."""

    id: int
    name: str
    kind: int | None
    job: int | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            name=_str(raw.get("name")),
            kind=_int_or_none(raw.get("kind")),
            job=_int_or_none(raw.get("job")),
            raw=dict(raw),
        )


@dataclass(frozen=True, slots=True)
class Job:
    """`GET /api/jobs` item."""

    id: int
    target_states: tuple[dict[str, Any], ...]
    scenes: tuple[int, ...]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            target_states=tuple(raw.get("target_states") or ()),
            scenes=tuple(int(x) for x in raw.get("scenes") or ()),
            raw=dict(raw),
        )


@dataclass(frozen=True, slots=True)
class Sensor:
    """`GET /api/sensors` item (an input of a device, e.g. one weather-station channel)."""

    id: int
    name: str
    type: SensorType
    raw_type: str
    unit: str
    value: Any
    device: str
    channel: int
    sub_type: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        raw_type = _str(raw.get("type"))
        try:
            sensor_type = SensorType(raw_type)
        except ValueError:
            sensor_type = SensorType.UNKNOWN
        return cls(
            id=int(raw["id"]),
            name=_str(raw.get("name")),
            type=sensor_type,
            raw_type=raw_type,
            unit=_str(raw.get("unit")),
            value=raw.get("value"),
            device=_str(raw.get("device")),
            channel=int(raw.get("channel", 0)),
            sub_type=_str(raw.get("sub_type")),
        )

    def with_value(self, value: Any) -> Sensor:
        """Return a copy with a new value (websocket frames only carry ``value``)."""
        return replace(self, value=value)

    @property
    def unique_key(self) -> str:
        """Stable key based on device and channel."""
        return f"{self.device}_{self.channel}"

    @property
    def numeric_value(self) -> float | None:
        """Value as float if possible."""
        return _float_or_none(self.value)

    @property
    def bool_value(self) -> bool:
        """Value as bool (rain/hail/window)."""
        return _bool(self.value)


@dataclass(frozen=True, slots=True)
class Button:
    """`GET /api/buttons` item; ``id`` is ``None`` until the button is registered."""

    id: int | None
    device: str
    channel: int
    type: str
    sub_type: str
    job: int | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=_int_or_none(raw.get("id")),
            device=_str(raw.get("device")),
            channel=int(raw.get("channel", 0)),
            type=_str(raw.get("type")),
            sub_type=_str(raw.get("sub_type")),
            job=_int_or_none(raw.get("job")),
        )

    @property
    def unique_key(self) -> str:
        """Stable key based on device and channel."""
        return f"{self.device}_button_{self.channel}"

    @property
    def registered(self) -> bool:
        """True if the gateway sends websocket events for this button."""
        return self.id is not None


@dataclass(frozen=True, slots=True)
class HvacGroup:
    """`GET /api/hvacgroups` item."""

    id: int
    name: str
    loads: tuple[int, ...]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            name=_str(raw.get("name")),
            loads=tuple(int(x) for x in raw.get("loads") or ()),
            raw=dict(raw),
        )


@dataclass(frozen=True, slots=True)
class HvacState:
    """`GET /api/hvacgroups/state` item."""

    ambient_temperature: float | None
    target_temperature: float | None
    unit: str
    flags: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Self:
        """Parse the raw dict."""
        raw = raw or {}
        return cls(
            ambient_temperature=_float_or_none(raw.get("ambient_temperature")),
            target_temperature=_float_or_none(raw.get("target_temperature")),
            unit=_str(raw.get("unit"), "C"),
            flags=dict(raw.get("flags") or {}),
            raw=dict(raw),
        )

    def merge(self, partial: dict[str, Any] | None) -> HvacState:
        """Apply a partial state on top of this one."""
        if not partial:
            return self
        merged = {**self.raw, **partial}
        if "flags" in partial:
            merged["flags"] = {**self.flags, **(partial.get("flags") or {})}
        return HvacState.from_api(merged)

    @property
    def output_on(self) -> bool:
        """True while the valve/output is active."""
        return _bool(self.flags.get("output_on", 0))

    @property
    def cooling(self) -> bool:
        """True if the group is in cooling mode."""
        return _bool(self.flags.get("cooling", 0))


@dataclass(frozen=True, slots=True)
class Flag:
    """`GET /api/system/flags` item (user defined boolean)."""

    id: int
    symbol: str
    value: bool
    name: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Self:
        """Parse the raw dict."""
        return cls(
            id=int(raw["id"]),
            symbol=_str(raw.get("symbol")),
            value=_bool(raw.get("value", False)),
            name=_str(raw.get("name")),
        )

    def with_value(self, value: bool) -> Flag:
        """Return a copy with a new value."""
        return replace(self, value=value)


def motor_kind_name(kind: int | None) -> str:
    """Readable name of a motor kind for diagnostics."""
    return {
        MotorKind.MOTOR: "motor",
        MotorKind.VENETIAN_BLINDS: "venetian_blinds",
        MotorKind.ROLLER_SHUTTERS: "roller_shutters",
        MotorKind.AWNINGS: "awnings",
    }.get(kind if kind is not None else -1, "unknown")
