"""Switches, generated from the SDK control fields."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
        YarboSwitch(coordinator, sn, cf, )
        for sn, device in coordinator.devices.items()
        for cf in control_fields(device.type_id, "switch")
    )


class YarboSwitch(YarboControlEntity, SwitchEntity):
    """A registry-defined switch."""

    def __init__(self, coordinator, sn, cf) -> None:
        super().__init__(coordinator, sn, "switch", cf)

    @property
    def is_on(self) -> bool | None:
        return self._current()

    @property
    def assumed_state(self) -> bool:
        # Some settings (geo fence, ignore obstacles) are never reported back.
        return self._actual() is None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send(False)
