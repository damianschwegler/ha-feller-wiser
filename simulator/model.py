"""In-memory model of a Wiser by Feller µGateway."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
import uuid

FIXTURES = Path(__file__).parent / "fixtures"

FrameListener = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class SimConfig:
    full_travel_s: float = 60.0
    tilt_ms_default: int = 250
    tick_s: float = 0.25
    claim_timeout_s: float = 30.0
    auto_press_after_s: float | None = None
    api_version: str = "2.0"
    sw_version: str = "6.0.46"


@dataclass
class Load:
    """Base class of all load types (an output channel)."""

    id: int
    name: str
    type: str
    sub_type: str = ""
    device: str = "00000000"
    channel: int = 0
    unused: bool = False
    room: int | None = None
    kind: int | None = None

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "sub_type": self.sub_type,
            "device": self.device,
            "channel": self.channel,
            "unused": self.unused,
        }
        if self.room is not None:
            out["room"] = self.room
        if self.kind is not None:
            out["kind"] = self.kind
        return out

    def state(self) -> dict[str, Any]:
        raise NotImplementedError

    def target_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def ctrl(self, button: str, event: str) -> None:
        raise NotImplementedError

    def tick(self, dt: float) -> dict[str, Any] | None:
        return None


@dataclass
class OnOffLoad(Load):
    bri: int = 0
    flags: dict[str, int] = field(default_factory=dict)

    def state(self) -> dict[str, Any]:
        return {"bri": self.bri}

    def target_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "bri" in payload:
            self.bri = 10000 if int(payload["bri"]) > 0 else 0
        return {"bri": self.bri}

    def ctrl(self, button: str, event: str) -> None:
        if button == "on":
            self.bri = 10000
        elif button == "off":
            self.bri = 0
        elif button == "toggle":
            self.bri = 0 if self.bri else 10000


@dataclass
class DimLoad(Load):
    bri: int = 0
    ct: int | None = None
    red: int | None = None
    green: int | None = None
    blue: int | None = None
    white: int | None = None
    flags: dict[str, int] = field(
        default_factory=lambda: {
            "over_current": 0,
            "fading": 0,
            "noise": 0,
            "direction": 0,
            "over_temperature": 0,
        }
    )

    def state(self) -> dict[str, Any]:
        out: dict[str, Any] = {"bri": self.bri, "flags": dict(self.flags)}
        if self.sub_type == "tw":
            out["ct"] = self.ct if self.ct is not None else 3000
        if self.sub_type == "rgb":
            out.update(
                red=self.red or 0,
                green=self.green or 0,
                blue=self.blue or 0,
                white=self.white or 0,
            )
        return out

    def target_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("bri", "ct", "red", "green", "blue", "white"):
            if key in payload:
                setattr(self, key, int(payload[key]))
        return dict(payload.items())

    def ctrl(self, button: str, event: str) -> None:
        if event == "click":
            if button in ("on", "up"):
                self.bri = 10000
            elif button in ("off", "down"):
                self.bri = 0
            elif button == "toggle":
                self.bri = 0 if self.bri else 10000


@dataclass
class ClaimState:
    """Pending claim waiting for a button press."""

    pressed: asyncio.Event = field(default_factory=asyncio.Event)
    active: bool = False


class GatewayModel:
    """Holds every object the simulated gateway knows about."""

    def __init__(self, config: SimConfig | None = None) -> None:
        self.config = config or SimConfig()
        self.info: dict[str, Any] = {}
        self.site: dict[str, Any] = {}
        self.net: dict[str, Any] = {}
        self.health: dict[str, Any] = {}
        self.loads: dict[int, Load] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.rooms: dict[int, dict[str, Any]] = {}
        self.scenes: dict[int, dict[str, Any]] = {}
        self.jobs: dict[int, dict[str, Any]] = {}
        self.sensors: dict[int, dict[str, Any]] = {}
        self.buttons: list[dict[str, Any]] = []
        self.hvacgroups: dict[int, dict[str, Any]] = {}
        self.hvac_states: dict[int, dict[str, Any]] = {}
        self.flags: dict[int, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, str] = {}
        self.claim = ClaimState()
        self.listeners: list[FrameListener] = []
        self.open_configs: dict[int, str] = {}
        self._config_counter = 100
        self._button_counter = 200
        self.clock = 0.0
        self.jobs_run: list[int] = []
        self.pings: list[int] = []

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_fixture(
        cls, path: str | Path | None = None, config: SimConfig | None = None
    ) -> GatewayModel:
        model = cls(config)
        fixture = Path(path) if path else FIXTURES / "home.json"
        model.load_fixture(json.loads(fixture.read_text(encoding="utf-8")))
        return model

    def load_fixture(self, data: dict[str, Any]) -> None:
        from .motor import MotorLoad

        cfg = self.config
        self.info = dict(data.get("info", {}))
        self.info.setdefault("api", cfg.api_version)
        self.info.setdefault("sw", cfg.sw_version)
        self.site = dict(data.get("site", {}))
        self.net = dict(data.get("net", {}))
        self.health = dict(data.get("health", {}))
        self.devices = {d["id"]: d for d in data.get("devices", [])}
        self.rooms = {r["id"]: r for r in data.get("rooms", [])}
        self.scenes = {s["id"]: s for s in data.get("scenes", [])}
        self.jobs = {j["id"]: j for j in data.get("jobs", [])}
        self.sensors = {s["id"]: s for s in data.get("sensors", [])}
        self.buttons = list(data.get("buttons", []))
        self.hvacgroups = {h["id"]: h for h in data.get("hvacgroups", [])}
        self.hvac_states = {h["id"]: h.pop("state", {}) for h in self.hvacgroups.values()}
        self.flags = {f["id"]: f for f in data.get("flags", [])}
        self.accounts = {a["user"]: a for a in data.get("accounts", [])}
        self.tokens = {}
        for account in self.accounts.values():
            if account.get("secret"):
                self.tokens[account["secret"]] = account["user"]
        self.loads = {}
        for raw in data.get("loads", []):
            common = {
                "id": raw["id"],
                "name": raw.get("name", f"{raw.get('device', '00000000')}_{raw.get('channel', 0)}"),
                "type": raw["type"],
                "sub_type": raw.get("sub_type", ""),
                "device": raw.get("device", "00000000"),
                "channel": raw.get("channel", 0),
                "unused": raw.get("unused", False),
                "room": raw.get("room"),
                "kind": raw.get("kind"),
            }
            state = raw.get("state", {})
            load: Load
            if raw["type"] == "motor":
                motor_cfg = self._motor_config(common["device"], common["channel"])
                load = MotorLoad(
                    **common,
                    level=int(state.get("level", 0)),
                    tilt=int(state.get("tilt", 0)),
                    tilt_ms=int(motor_cfg.get("tilt_ms", cfg.tilt_ms_default)),
                    tiltable=bool(motor_cfg.get("tiltable", True)),
                    speed=10000 / cfg.full_travel_s,
                )
                for key, value in (state.get("flags") or {}).items():
                    load.flags[key] = value
            elif raw["type"] == "onoff":
                load = OnOffLoad(**common, bri=int(state.get("bri", 0)))
            else:
                load = DimLoad(
                    **common,
                    bri=int(state.get("bri", 0)),
                    ct=state.get("ct"),
                    red=state.get("red"),
                    green=state.get("green"),
                    blue=state.get("blue"),
                    white=state.get("white"),
                )
            self.loads[load.id] = load

    def _motor_config(self, device_id: str, channel: int) -> dict[str, Any]:
        device = self.devices.get(device_id) or {}
        outputs = device.get("outputs") or []
        if channel < len(outputs):
            return dict(outputs[channel].get("config") or {})
        return {}

    # ------------------------------------------------------------------ accounts
    def valid_token(self, token: str | None) -> bool:
        return bool(token) and token in self.tokens

    def create_token(self, user: str, source: str | None) -> dict[str, Any]:
        # re-claiming the same user replaces the previous secret
        for secret, owner in list(self.tokens.items()):
            if owner == user:
                del self.tokens[secret]
        secret = str(uuid.uuid4())
        self.tokens[secret] = user
        account = {"user": user, "secret": secret}
        if source:
            account["source"] = source
        self.accounts[user] = account
        return account

    def revoke_all_tokens(self) -> None:
        self.tokens.clear()

    def press_button(self) -> None:
        """Simulate a physical button press on the gateway (completes a claim)."""
        self.claim.pressed.set()

    # ------------------------------------------------------------------ devices
    def device_basic(self, device: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in device.items() if k in ("id", "last_seen", "a", "c")}

    def device_detailed(self, device: dict[str, Any]) -> dict[str, Any]:
        out = self.device_basic(device)
        out["inputs"] = [{"type": i.get("type", "up down")} for i in device.get("inputs", [])]
        out["outputs"] = [
            {"load": o.get("load"), "type": o.get("type"), "sub_type": o.get("sub_type", "")}
            for o in device.get("outputs", [])
        ]
        return out

    def open_device_config(self, device_id: str) -> dict[str, Any]:
        device = self.devices[device_id]
        self._config_counter += 1
        cfg_id = self._config_counter
        self.open_configs[cfg_id] = device_id
        outputs = []
        for o in device.get("outputs", []):
            entry = {"type": o.get("type"), "sub_type": o.get("sub_type", "")}
            entry.update(o.get("config") or {})
            outputs.append(entry)
        inputs = [dict(i) for i in device.get("inputs", [])]
        return {"id": cfg_id, "device": device_id, "outputs": outputs, "inputs": inputs}

    def close_device_config(self, cfg_id: int) -> bool:
        return self.open_configs.pop(cfg_id, None) is not None

    # ------------------------------------------------------------------ buttons
    def register_button(self, device: str, channel: int) -> dict[str, Any]:
        for button in self.buttons:
            if button["device"] == device and button["channel"] == channel:
                if button.get("id") is None:
                    self._button_counter += 1
                    button["id"] = self._button_counter
                return button
        self._button_counter += 1
        button = {
            "id": self._button_counter,
            "device": device,
            "channel": channel,
            "type": "button",
            "sub_type": "up down",
        }
        self.buttons.append(button)
        return button

    # ------------------------------------------------------------------ frames
    async def emit(self, frame: dict[str, Any]) -> None:
        for listener in list(self.listeners):
            await listener(frame)

    def load_frame(self, load_id: int, state: dict[str, Any] | None = None) -> dict[str, Any]:
        load = self.loads[load_id]
        return {"load": {"id": load_id, "state": state if state is not None else load.state()}}

    def advance(self, dt: float) -> list[dict[str, Any]]:
        """Advance the simulated clock and return the frames to broadcast."""
        self.clock += dt
        frames: list[dict[str, Any]] = []
        for load in self.loads.values():
            changed = load.tick(dt)
            if changed:
                frames.append(self.load_frame(load.id, changed))
        return frames

    async def advance_and_emit(self, dt: float) -> list[dict[str, Any]]:
        frames = self.advance(dt)
        for frame in frames:
            await self.emit(frame)
        return frames

    async def apply_target_state(self, load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        load = self.loads[load_id]
        applied = load.target_state(payload)
        # start the plan so the first frame already shows "moving"
        changed = load.tick(0.0)
        await self.emit(self.load_frame(load_id, changed or load.state()))
        return applied

    async def apply_ctrl(self, load_id: int, button: str, event: str) -> None:
        load = self.loads[load_id]
        load.ctrl(button, event)
        changed = load.tick(0.0)
        await self.emit(self.load_frame(load_id, changed or load.state()))

    async def set_load_state(self, load_id: int, state: dict[str, Any]) -> None:
        """Force a state (as if a wall switch was used) and push it."""
        load = self.loads[load_id]
        for key, value in state.items():
            if key == "flags" and hasattr(load, "flags"):
                load.flags.update(value)  # type: ignore[attr-defined]
            elif hasattr(load, key):
                setattr(load, key, value)
        if hasattr(load, "plan"):
            load.plan.clear()  # type: ignore[attr-defined]
        await self.emit(self.load_frame(load_id, state))

    async def set_sensor_value(self, sensor_id: int, value: Any) -> None:
        self.sensors[sensor_id]["value"] = value
        await self.emit({"sensor": {"id": sensor_id, "value": value}})

    async def press_physical_button(
        self, button_id: int, event: str, type_: str = "up down"
    ) -> None:
        await self.emit({"button": {"id": button_id, "cmd": {"event": event, "type": type_}}})

    async def set_flag(self, flag_id: int, value: bool) -> dict[str, Any]:
        flag = self.flags[flag_id]
        flag["value"] = bool(value)
        await self.emit({"flag": dict(flag)})
        return flag

    async def set_hvac_target(self, group_id: int, target: float) -> None:
        state = self.hvac_states.setdefault(group_id, {})
        state["target_temperature"] = target
        await self.emit({"hvacgroup": {"id": group_id, "state": {"target_temperature": target}}})
