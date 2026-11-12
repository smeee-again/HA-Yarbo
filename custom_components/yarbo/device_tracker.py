"""GPS position of the robot (local odometry + GPS reference origin)."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import YarboConfigEntry, YarboCoordinator
from .entity import YarboEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(YarboTracker(coordinator, sn) for sn in coordinator.devices)


class YarboTracker(YarboEntity, TrackerEntity):
    """Robot location."""

    _attr_name = "Location"
    _attr_icon = "mdi:robot-mower"

    def __init__(self, coordinator: YarboCoordinator, sn: str) -> None:
        super().__init__(coordinator, sn, "device_tracker", "location")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.device_location(self._sn) is not None

    @property
    def latitude(self) -> float | None:
        location = self.coordinator.device_location(self._sn)
        return location[0] if location else None

    @property
    def longitude(self) -> float | None:
        location = self.coordinator.device_location(self._sn)
        return location[1] if location else None
