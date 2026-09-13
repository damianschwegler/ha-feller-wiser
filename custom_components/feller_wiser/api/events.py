"""Typed websocket frames.

The gateway sends one JSON object per text frame without an envelope, e.g.
``{"load": {"id": 3, "state": {"moving": "stop", "tilt": 0, "level": 8160}}}``.
Only changes are transmitted, so ``state`` dicts are partial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WsEvent:
    """Base class of all websocket events."""

    raw: dict[str, Any] = field(default_factory=dict, kw_only=True)


@dataclass(frozen=True, slots=True)
class LoadEvent(WsEvent):
    """Partial state update of a load."""

    id: int
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SensorEvent(WsEvent):
    """Partial update of a sensor (usually only ``value``)."""

    id: int
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HvacEvent(WsEvent):
    """Partial state update of an HVAC group."""

    id: int
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FlagEvent(WsEvent):
    """A system flag changed (full flag object)."""

    id: int
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ButtonEvent(WsEvent):
    """A registered physical button was used."""

    id: int
    event: str
    type: str | None


@dataclass(frozen=True, slots=True)
class FindMeEvent(WsEvent):
    """A button was pressed while find-me mode was active."""

    target: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WestgroupEvent(WsEvent):
    """Weather protection event."""

    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UnknownEvent(WsEvent):
    """Anything we do not understand yet."""

    key: str


def parse_ws_frame(raw: dict[str, Any]) -> WsEvent | None:
    """Turn a decoded frame into an event, ``None`` for empty/invalid frames."""
    if not isinstance(raw, dict) or not raw:
        return None
    if "load" in raw:
        load = raw["load"]
        if isinstance(load, dict) and "id" in load:
            return LoadEvent(id=int(load["id"]), state=dict(load.get("state") or {}), raw=raw)
    if "sensor" in raw:
        sensor = raw["sensor"]
        if isinstance(sensor, dict) and "id" in sensor:
            data = {k: v for k, v in sensor.items() if k != "id"}
            return SensorEvent(id=int(sensor["id"]), data=data, raw=raw)
    if "hvacgroup" in raw:
        hvac = raw["hvacgroup"]
        if isinstance(hvac, dict) and "id" in hvac:
            return HvacEvent(id=int(hvac["id"]), state=dict(hvac.get("state") or {}), raw=raw)
    if "flag" in raw:
        flag = raw["flag"]
        if isinstance(flag, dict) and "id" in flag:
            return FlagEvent(id=int(flag["id"]), data=dict(flag), raw=raw)
    if "button" in raw:
        button = raw["button"]
        if isinstance(button, dict) and button.get("id") is not None:
            cmd = button.get("cmd") or {}
            event = cmd.get("event")
            if event:
                return ButtonEvent(
                    id=int(button["id"]), event=str(event), type=cmd.get("type"), raw=raw
                )
    if "findme" in raw:
        findme = raw["findme"]
        return FindMeEvent(target=dict(findme) if isinstance(findme, dict) else {}, raw=raw)
    if "westgroup" in raw:
        west = raw["westgroup"]
        return WestgroupEvent(data=dict(west) if isinstance(west, dict) else {}, raw=raw)
    return UnknownEvent(key=next(iter(raw)), raw=raw)
