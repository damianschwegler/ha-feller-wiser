"""Runtime data structures shared by the integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

from .api import (
    Button,
    Device,
    Flag,
    Health,
    HvacGroup,
    HvacState,
    Info,
    Job,
    Load,
    LoadState,
    MotorOutputConfig,
    NetState,
    Room,
    Scene,
    Sensor,
    Site,
    WiserClient,
    WiserWebSocket,
)

if TYPE_CHECKING:
    from .coordinator import WiserCoordinator
    from .tilt_controller import TiltController


@dataclass
class WiserData:
    """Everything the coordinator knows about one gateway."""

    info: Info
    site: Site
    net: NetState | None = None
    loads: dict[int, Load] = field(default_factory=dict)
    load_states: dict[int, LoadState] = field(default_factory=dict)
    devices: dict[str, Device] = field(default_factory=dict)
    motor_configs: dict[str, MotorOutputConfig] = field(default_factory=dict)
    """Keyed by ``f"{device}_{channel}"``."""
    rooms: dict[int, Room] = field(default_factory=dict)
    scenes: dict[int, Scene] = field(default_factory=dict)
    jobs: dict[int, Job] = field(default_factory=dict)
    sensors: dict[int, Sensor] = field(default_factory=dict)
    buttons: dict[str, Button] = field(default_factory=dict)
    """Keyed by ``Button.unique_key``."""
    hvac_groups: dict[int, HvacGroup] = field(default_factory=dict)
    hvac_states: dict[int, HvacState] = field(default_factory=dict)
    flags: dict[int, Flag] = field(default_factory=dict)
    health: Health | None = None
    rssi: int | None = None
    ws_connected: bool = False
    buttons_supported: bool = True
    details_complete: bool = False
    details_failed: set[str] = field(default_factory=set)
    structure_version: int = 0

    def room_name(self, room_id: int | None) -> str | None:
        """Name of a room, ``None`` if unknown."""
        if room_id is None:
            return None
        room = self.rooms.get(room_id)
        return room.name if room else None

    def loads_of_device(self, device_id: str) -> list[Load]:
        """All loads driven by a physical device."""
        return [load for load in self.loads.values() if load.device == device_id]

    def motor_config(self, load: Load) -> MotorOutputConfig | None:
        """Cached motor configuration for a load."""
        return self.motor_configs.get(load.unique_key)


@dataclass
class WiserRuntimeData:
    """Stored on ``entry.runtime_data``."""

    client: WiserClient
    coordinator: WiserCoordinator
    websocket: WiserWebSocket
    tilt_controllers: dict[int, TiltController] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


type WiserConfigEntry = ConfigEntry[WiserRuntimeData]
