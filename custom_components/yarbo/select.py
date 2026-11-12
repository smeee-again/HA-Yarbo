"""Selects: working state (from the registry) and the plan to run."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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
            YarboSelect(coordinator, sn, cf)
            for cf in control_fields(device.type_id, "select")
        )
        entities.append(YarboPlanSelect(coordinator, sn))
    async_add_entities(entities)


class YarboSelect(YarboControlEntity, SelectEntity):
    """A registry-defined select (working state)."""

    def __init__(self, coordinator, sn, cf) -> None:
        super().__init__(coordinator, sn, "select", cf)
        self._attr_options = list(cf.options or [])

    @property
    def current_option(self) -> str | None:
        return self._current()

    async def async_select_option(self, option: str) -> None:
        await self._async_send(option)


class YarboPlanSelect(YarboEntity, SelectEntity):
    """Choose which automatic plan 'Start' on the lawn mower entity runs."""

    _attr_name = "Plan"
    _attr_icon = "mdi:clipboard-list"

    def __init__(self, coordinator: YarboCoordinator, sn: str) -> None:
        super().__init__(coordinator, sn, "select", "plan")

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.plan_labels(self._sn))

    @property
    def current_option(self) -> str | None:
        selected = self.coordinator.resolve_plan_id(self._sn)
        for label, plan_id in self.coordinator.plan_labels(self._sn).items():
            if plan_id == selected:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        plan_id = self.coordinator.plan_labels(self._sn).get(option)
        if plan_id is None:
            raise ServiceValidationError(f"Unknown plan: {option}")
        self.coordinator.selected_plan[self._sn] = plan_id
        self.async_write_ha_state()
