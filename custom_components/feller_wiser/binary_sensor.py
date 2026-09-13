"""Binary sensor platform: rain/hail/window inputs, motor problems, websocket status."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .api import Device, Load, LoadType, Sensor, SensorType
from .const import SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserEntity, WiserGatewayEntity, WiserLoadEntity
from .naming import gateway_registry_id, wiser_device_info

PARALLEL_UPDATES = 1

BOOL_TYPES: dict[SensorType, BinarySensorDeviceClass] = {
    SensorType.RAIN: BinarySensorDeviceClass.MOISTURE,
    SensorType.HAIL: BinarySensorDeviceClass.MOISTURE,
    SensorType.WINDOW: BinarySensorDeviceClass.WINDOW,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create binary sensors."""
    coordinator = entry.runtime_data.coordinator
    known_sensors: set[int] = set()
    known_loads: set[int] = set()

    async_add_entities([WiserWebsocketSensor(coordinator)])

    @callback
    def _add_new() -> None:
        new: list[BinarySensorEntity] = []
        for sensor in coordinator.data.sensors.values():
            if sensor.id in known_sensors or sensor.type not in BOOL_TYPES:
                continue
            known_sensors.add(sensor.id)
            new.append(WiserBinarySensor(coordinator, sensor.id))
        for load in coordinator.data.loads.values():
            if load.id in known_loads or load.type is not LoadType.MOTOR:
                continue
            known_loads.add(load.id)
            new.append(WiserMotorProblemSensor(coordinator, load))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserBinarySensor(WiserEntity, BinarySensorEntity):
    """Boolean Wiser sensor input."""

    def __init__(self, coordinator: WiserCoordinator, sensor_id: int) -> None:
        """Unique id ``{device}_{channel}_sensor_{type}``."""
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        sensor = coordinator.data.sensors[sensor_id]
        self._attr_unique_id = f"{sensor.unique_key}_sensor_{sensor.raw_type}"
        self._attr_device_class = BOOL_TYPES[sensor.type]
        if sensor.type is SensorType.HAIL:
            self._attr_icon = "mdi:weather-hail"
        self._attr_name = (
            sensor.name if sensor.name and not sensor.name.startswith(sensor.device) else None
        )
        if self._attr_name is None:
            self._attr_translation_key = f"sensor_{sensor.raw_type.lower()}"
        else:
            domain = type(self).__module__.rsplit(".", 1)[-1]
            self.entity_id = f"{domain}.{slugify(self._attr_name)}"

    @property
    def sensor(self) -> Sensor | None:
        """Current sensor object."""
        return self.data.sensors.get(self._sensor_id)

    @property
    def available(self) -> bool:
        """Only while the sensor exists."""
        return super().available and self.sensor is not None

    @property
    def is_on(self) -> bool | None:
        """Boolean value."""
        sensor = self.sensor
        return None if sensor is None else sensor.bool_value

    @property
    def device_info(self) -> DeviceInfo:
        """The device providing the input."""
        sensor = self.sensor
        device_id = sensor.device if sensor else ""
        device = self.data.devices.get(device_id) or Device.from_api({"id": device_id})
        return wiser_device_info(
            self.data,
            device,
            rooms_as_areas=self.rooms_as_areas,
            via_device_id=gateway_registry_id(self.hass, self.data),
        )


class WiserMotorProblemSensor(WiserLoadEntity, BinarySensorEntity):
    """Fault flags of a motor (over/under current, timeout)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "motor_problem"

    def __init__(self, coordinator: WiserCoordinator, load: Load) -> None:
        """Unique id ``{device}_{channel}_problem``."""
        super().__init__(coordinator, load, "_problem")

    @property
    def is_on(self) -> bool | None:
        """Any fault flag set."""
        state = self.state_data
        return None if state is None else state.flags.has_problem

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which flags are set."""
        state = self.state_data
        if state is None:
            return {}
        flags = state.flags
        return {
            "under_current": flags.under_current,
            "over_current": flags.over_current,
            "timeout": flags.timeout,
            "learning": flags.learning,
            "locked": flags.locked,
        }


class WiserWebsocketSensor(WiserGatewayEntity, BinarySensorEntity):
    """Push connection to the gateway."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "websocket_connected"

    def __init__(self, coordinator: WiserCoordinator) -> None:
        """Unique id ``{sn}_websocket``."""
        super().__init__(coordinator, "websocket")

    @property
    def available(self) -> bool:
        """Always available; the state says whether push works."""
        return True

    @property
    def is_on(self) -> bool:
        """Connected."""
        return self.data.ws_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Connection counters."""
        return self.coordinator.ws_stats()
