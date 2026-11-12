"""Sensors, generated from the SDK device registry."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from yarbo_robot_sdk.models import FieldDefinition

from .const import DIAGNOSTIC_PATHS, DIAGNOSTIC_PREFIXES, NAME_OVERRIDES
from .coordinator import YarboConfigEntry, YarboCoordinator
from .entity import YarboEntity
from .helpers import control_fields, extract_status_value, sensor_options, status_fields


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[YarboSensor] = []
    for sn, device in coordinator.devices.items():
        # A control entity already shows the state of its own path.
        control_paths = {cf.path for cf in control_fields(device.type_id)}
        entities.extend(
            YarboSensor(coordinator, sn, fdef)
            for fdef in status_fields(device.type_id, "sensor")
            if fdef.path not in control_paths
        )
    async_add_entities(entities)


class YarboSensor(YarboEntity, SensorEntity):
    """A registry-defined sensor."""

    def __init__(
        self, coordinator: YarboCoordinator, sn: str, fdef: FieldDefinition
    ) -> None:
        super().__init__(coordinator, sn, "sensor", fdef.name)
        self._fdef = fdef
        self._attr_name = NAME_OVERRIDES.get(fdef.name, fdef.name)
        self._attr_icon = fdef.icon
        self._attr_native_unit_of_measurement = fdef.unit
        self._attr_entity_registry_enabled_default = fdef.enabled_by_default
        if fdef.path in DIAGNOSTIC_PATHS or fdef.path.startswith(DIAGNOSTIC_PREFIXES):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        options = sensor_options(fdef)
        if options:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = options
        elif fdef.device_class and fdef.device_class != "enum":
            try:
                self._attr_device_class = SensorDeviceClass(fdef.device_class)
            except ValueError:
                pass
        if fdef.unit and not options:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return extract_status_value(self._fdef, self.device_data)
