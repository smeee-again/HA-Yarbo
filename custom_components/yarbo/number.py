"""Numbers, generated from the SDK control fields."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import YarboConfigEntry
from .entity import YarboControlEntity
from .helpers import control_fields


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        YarboNumber(coordinator, sn, cf)
        for sn, device in coordinator.devices.items()
        for cf in control_fields(device.type_id, "number")
    )


class YarboNumber(YarboControlEntity, NumberEntity):
    """A registry-defined number (volume, blade height, chute angle ...)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, sn, cf) -> None:
        super().__init__(coordinator, sn, "number", cf)
        self._attr_native_min_value = cf.min_value if cf.min_value is not None else 0
        self._attr_native_max_value = cf.max_value if cf.max_value is not None else 100
        self._attr_native_step = cf.step or 1
        self._attr_native_unit_of_measurement = cf.unit
        if cf.command_builder == "sound_volume":
            self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        return self._current()

    async def async_set_native_value(self, value: float) -> None:
        await self._async_send(value)
