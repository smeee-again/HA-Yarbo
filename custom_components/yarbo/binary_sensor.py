"""Binary sensors, generated from the SDK device registry."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from yarbo_robot_sdk.models import FieldDefinition

from .const import NAME_OVERRIDES
from .coordinator import YarboConfigEntry, YarboCoordinator
from .entity import YarboEntity
from .helpers import control_fields, extract_status_value, status_fields


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[YarboEntity] = []
    for sn, device in coordinator.devices.items():
        entities.append(YarboOnlineBinarySensor(coordinator, sn))
        control_paths = {cf.path for cf in control_fields(device.type_id)}
        entities.extend(
            YarboBinarySensor(coordinator, sn, fdef)
            for fdef in status_fields(device.type_id, "binary_sensor")
            if fdef.path not in control_paths
        )
    async_add_entities(entities)


class YarboBinarySensor(YarboEntity, BinarySensorEntity):
    """A registry-defined binary sensor."""

    def __init__(
        self, coordinator: YarboCoordinator, sn: str, fdef: FieldDefinition
    ) -> None:
        super().__init__(coordinator, sn, "binary_sensor", fdef.name)
        self._fdef = fdef
        self._attr_name = NAME_OVERRIDES.get(fdef.name, fdef.name)
        self._attr_icon = fdef.icon
        self._attr_entity_registry_enabled_default = fdef.enabled_by_default
        if fdef.device_class:
            try:
                self._attr_device_class = BinarySensorDeviceClass(fdef.device_class)
            except ValueError:
                pass

    @property
    def is_on(self) -> bool | None:
        return extract_status_value(self._fdef, self.device_data)


class YarboOnlineBinarySensor(YarboEntity, BinarySensorEntity):
    """Whether the robot is reachable (recent MQTT traffic or cloud 'online')."""

    _always_available = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: YarboCoordinator, sn: str) -> None:
        super().__init__(coordinator, sn, "binary_sensor", "online")

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_online(self._sn)
