"""The Yarbo integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from yarbo_robot_sdk.exceptions import AuthenticationError, YarboSDKError

from .coordinator import YarboConfigEntry, YarboCoordinator
from .helpers import connect

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.LAWN_MOWER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: YarboConfigEntry) -> bool:
    """Log in, subscribe to every robot and set up the platforms."""
    try:
        client, devices = await hass.async_add_executor_job(
            connect, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("Invalid Yarbo credentials") from err
    except YarboSDKError as err:
        raise ConfigEntryNotReady(f"Cannot reach Yarbo cloud: {err}") from err

    if not devices:
        await hass.async_add_executor_job(client.close)
        raise ConfigEntryNotReady("No Yarbo devices found on this account")

    coordinator = YarboCoordinator(hass, entry, client, devices)
    try:
        await coordinator.async_start()
    except Exception:
        await hass.async_add_executor_job(client.close)
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_stop)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YarboConfigEntry) -> bool:
    """Unload platforms; the coordinator stops via ``async_on_unload``."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
