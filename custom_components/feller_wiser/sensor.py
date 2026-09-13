"""Sensor platform: Wiser sensors (weather station, thermostats) and gateway diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .api import Device, Sensor, SensorType
from .const import SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry, WiserData
from .entity import WiserEntity, WiserGatewayEntity
from .naming import gateway_registry_id, wiser_device_info

PARALLEL_UPDATES = 1

NUMERIC_TYPES: dict[SensorType, tuple[SensorDeviceClass | None, str | None]] = {
    SensorType.TEMPERATURE: (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    SensorType.ILLUMINANCE: (SensorDeviceClass.ILLUMINANCE, "lx"),
    SensorType.BRIGHTNESS: (SensorDeviceClass.ILLUMINANCE, "lx"),
    SensorType.WIND: (SensorDeviceClass.WIND_SPEED, UnitOfSpeed.METERS_PER_SECOND),
    SensorType.HUMIDITY: (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    SensorType.CO2: (SensorDeviceClass.CO2, CONCENTRATION_PARTS_PER_MILLION),
}


def _unit_for(sensor: Sensor) -> str | None:
    unit = sensor.unit.strip()
    if unit in ("℃", "°C", "C"):
        return UnitOfTemperature.CELSIUS
    if unit in ("lux", "lx"):
        return "lx"
    if unit in ("bool", ""):
        return None
    return unit


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription(SensorEntityDescription):
    """Gateway diagnostic sensor."""

    value_fn: Callable[[WiserData], Any]


GATEWAY_SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.rssi,
    ),
    GatewaySensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.uptime if d.health else None,
    ),
    GatewaySensorDescription(
        key="mem_free",
        translation_key="mem_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.mem_free if d.health else None,
    ),
    GatewaySensorDescription(
        key="wlan_resets",
        translation_key="wlan_resets",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.wlan_resets if d.health else None,
    ),
    GatewaySensorDescription(
        key="sockets",
        translation_key="sockets",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.sockets if d.health else None,
    ),
)

_ = (UnitOfDataRate,)  # keep import list stable for future data-rate sensors


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create sensor entities."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    async_add_entities(WiserGatewaySensor(coordinator, desc) for desc in GATEWAY_SENSORS)

    @callback
    def _add_new() -> None:
        new = []
        for sensor in coordinator.data.sensors.values():
            if sensor.id in known or sensor.type not in NUMERIC_TYPES:
                continue
            known.add(sensor.id)
            new.append(WiserSensor(coordinator, sensor.id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserSensor(WiserEntity, SensorEntity):
    """Numeric Wiser sensor input."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WiserCoordinator, sensor_id: int) -> None:
        """Unique id ``{device}_{channel}_sensor_{type}``."""
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        sensor = coordinator.data.sensors[sensor_id]
        self._attr_unique_id = f"{sensor.unique_key}_sensor_{sensor.raw_type}"
        device_class, default_unit = NUMERIC_TYPES[sensor.type]
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = _unit_for(sensor) or default_unit
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
    def native_value(self) -> float | None:
        """Numeric value."""
        sensor = self.sensor
        return None if sensor is None else sensor.numeric_value

    @property
    def device_info(self) -> DeviceInfo:
        """The device providing the input (weather station, thermostat)."""
        sensor = self.sensor
        device_id = sensor.device if sensor else ""
        device = self.data.devices.get(device_id) or Device.from_api({"id": device_id})
        return wiser_device_info(
            self.data,
            device,
            rooms_as_areas=self.rooms_as_areas,
            via_device_id=gateway_registry_id(self.hass, self.data),
        )


class WiserGatewaySensor(WiserGatewayEntity, SensorEntity):
    """Gateway health value."""

    entity_description: GatewaySensorDescription

    def __init__(
        self, coordinator: WiserCoordinator, description: GatewaySensorDescription
    ) -> None:
        """Unique id ``{sn}_{key}``."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Value from the coordinator data."""
        return self.entity_description.value_fn(self.data)
