"""Buttons: registry actions (play sound, emergency stop ...) plus plan refresh."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import YarboConfigEntry, YarboCoordinator
from .entity import YarboControlEntity, YarboEntity
from .helpers import control_fields


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[YarboEntity] = []
    for sn, device in coordinator.devices.items():
        entities.extend(
            YarboButton(coordinator, sn, cf)
            for cf in control_fields(device.type_id, "button")
        )
        entities.append(YarboRefreshPlansButton(coordinator, sn))
    async_add_entities(entities)


class YarboButton(YarboControlEntity, ButtonEntity):
    """A registry-defined action button."""

    def __init__(self, coordinator, sn, cf) -> None:
        super().__init__(coordinator, sn, "button", cf)

    async def async_press(self) -> None:
        await self.coordinator.async_send_control(self._sn, self._cf)


class YarboRefreshPlansButton(YarboEntity, ButtonEntity):
    """Re-read the automatic plans stored on the robot."""

    _attr_name = "Refresh Plans"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: YarboCoordinator, sn: str) -> None:
        super().__init__(coordinator, sn, "button", "refresh_plans")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_plans(self._sn)
