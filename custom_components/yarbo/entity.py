"""Base entities for the Yarbo integration."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify
from yarbo_robot_sdk.models import ControlFieldDefinition

from .const import CONFIG_CONTROL_PATHS, DOMAIN, MANUFACTURER
from .coordinator import YarboCoordinator
from .helpers import Optimistic, is_control_available, read_control_value


class YarboEntity(CoordinatorEntity[YarboCoordinator]):
    """Entity tied to one robot."""

    _attr_has_entity_name = True
    _always_available = False

    def __init__(self, coordinator: YarboCoordinator, sn: str, platform: str, key: str):
        super().__init__(coordinator)
        self._sn = sn
        device = coordinator.devices[sn]
        self._attr_unique_id = f"{sn}_{platform}_{slugify(key)}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            manufacturer=MANUFACTURER,
            model=device.model or device.type_id,
            name=device.name or f"Yarbo {sn}",
            serial_number=sn,
        )

    @property
    def device_data(self) -> dict[str, Any]:
        """Merged MQTT data for this robot."""
        return (self.coordinator.data or {}).get(self._sn, {})

    @property
    def available(self) -> bool:
        return super().available and (
            self._always_available or self.coordinator.is_online(self._sn)
        )


class YarboControlEntity(YarboEntity):
    """Entity driven by a registry control field (switch/number/select/button)."""

    def __init__(
        self,
        coordinator: YarboCoordinator,
        sn: str,
        platform: str,
        cf: ControlFieldDefinition,
    ) -> None:
        super().__init__(coordinator, sn, platform, cf.name)
        self._cf = cf
        self._optimistic = Optimistic()
        self._attr_name = cf.name
        self._attr_icon = cf.icon
        self._attr_entity_registry_enabled_default = cf.enabled_by_default
        if cf.path in CONFIG_CONTROL_PATHS:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return super().available and is_control_available(self._cf, self.device_data)

    def _actual(self) -> Any:
        return read_control_value(self._cf, self.device_data)

    def _current(self) -> Any:
        return self._optimistic.resolve(self._actual())

    async def _async_send(self, value: Any) -> None:
        await self.coordinator.async_send_control(self._sn, self._cf, value)
        self._optimistic.set(value)
        self.async_write_ha_state()
