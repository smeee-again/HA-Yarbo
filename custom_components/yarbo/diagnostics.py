"""Diagnostics for the Yarbo integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import YarboConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "sn", "head_sn", "latitude", "longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: YarboConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics (serial numbers become device_N)."""
    coordinator = entry.runtime_data
    devices: dict[str, Any] = {}
    for index, (sn, device) in enumerate(coordinator.devices.items()):
        devices[f"device_{index}"] = {
            "type_id": device.type_id,
            "model": device.model,
            "online_rest": device.online,
            "online": coordinator.is_online(sn),
            "plans": len(coordinator.plans.get(sn, [])),
            "has_gps_ref": sn in coordinator.gps_ref,
            "data": async_redact_data(coordinator.data.get(sn, {}), TO_REDACT),
        }
    return {"entry": async_redact_data(dict(entry.data), TO_REDACT), "devices": devices}
