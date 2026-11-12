"""Lawn mower entity: the main start / pause / dock control for the robot."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from yarbo_robot_sdk import extract_field

from .const import SERVICE_SEND_COMMAND, SERVICE_START_PLAN
from .coordinator import YarboConfigEntry, YarboCoordinator
from .entity import YarboEntity
from .helpers import control_topic_names, is_paused, mower_activity

ACTIVITY_MAP = {
    "error": LawnMowerActivity.ERROR,
    "returning": LawnMowerActivity.RETURNING,
    "mowing": LawnMowerActivity.MOWING,
    "docked": LawnMowerActivity.DOCKED,
    "paused": LawnMowerActivity.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YarboConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(YarboLawnMower(coordinator, sn) for sn in coordinator.devices)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_START_PLAN,
        {
            vol.Required("plan_id"): vol.Coerce(int),
            vol.Optional("start_percent", default=0): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=100)
            ),
        },
        "async_start_plan",
    )
    platform.async_register_entity_service(
        SERVICE_SEND_COMMAND,
        {
            vol.Required("command"): cv.string,
            vol.Optional("payload", default={}): dict,
        },
        "async_send_raw_command",
    )


class YarboLawnMower(YarboEntity, LawnMowerEntity):
    """The robot as a lawn mower (works with any attachment)."""

    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: YarboCoordinator, sn: str) -> None:
        super().__init__(coordinator, sn, "lawn_mower", "mower")

    @property
    def activity(self) -> LawnMowerActivity | None:
        key = mower_activity(self.device_data)
        return ACTIVITY_MAP.get(key) if key else None

    async def async_start_mowing(self) -> None:
        """Resume if paused, otherwise start the selected plan."""
        if self.activity is LawnMowerActivity.PAUSED and is_paused(
            extract_field(self.device_data, "StateMSG.planning_paused")
        ):
            await self.coordinator.async_send_command(self._sn, "resume", {})
            return
        plan_id = self.coordinator.resolve_plan_id(self._sn)
        if plan_id is None:
            raise ServiceValidationError(
                "No plan selected. Pick one with the 'Plan' select entity "
                "(press 'Refresh Plans' if it is empty) or call yarbo.start_plan."
            )
        await self.async_start_plan(plan_id)

    async def async_pause(self) -> None:
        await self.coordinator.async_send_command(self._sn, "pause", {})

    async def async_dock(self) -> None:
        await self.coordinator.async_send_command(self._sn, "cmd_recharge", {})

    async def async_start_plan(self, plan_id: int, start_percent: int = 0) -> None:
        """Service: start an automatic plan."""
        payload: dict[str, Any] = {"id": plan_id}
        if start_percent:
            payload["percent"] = start_percent
        await self.coordinator.async_send_command(self._sn, "start_plan", payload)

    async def async_send_raw_command(
        self, command: str, payload: dict[str, Any]
    ) -> None:
        """Service: publish any registered command topic (fallback for unlisted commands)."""
        device = self.coordinator.devices[self._sn]
        if command not in control_topic_names(device.type_id):
            raise ServiceValidationError(f"Unknown Yarbo command: {command}")
        await self.coordinator.async_send_command(self._sn, command, payload)
