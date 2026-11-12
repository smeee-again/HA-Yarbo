"""Home Assistant-independent logic for the Yarbo integration.

The SDK's device registry (``yarbo_Y.json``) names *extractors* and *command
builders* (``battery_capacity``, ``sound_volume`` ...) but does not implement
them, because they are meant to live in the Home Assistant integration. They
are implemented here.

Nothing in this module imports Home Assistant, so it can be unit tested on its
own.

ASSUMPTIONS TO VERIFY against a real robot are marked ``ASSUMPTION`` below.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from yarbo_robot_sdk import YarboClient, extract_active_network, extract_field
from yarbo_robot_sdk.device_registry import get_device_type
from yarbo_robot_sdk.models import ControlFieldDefinition, Device, FieldDefinition

_LOGGER = logging.getLogger(__name__)

# ASSUMPTION: BatteryMSG.status >= 1 means "charging".
CHARGING_STATUS_MIN = 1
# ASSUMPTION: RTK quality follows NMEA GGA fix quality (4 = RTK fixed,
# 5 = RTK float, 1/2 = GPS/DGPS). Already-textual values pass through.
RTK_QUALITY = {4: "Strong", 5: "Medium", 1: "Weak", 2: "Weak"}
# ASSUMPTION: StateMSG.volume is either 0-1 (SDK command scale) or 0-100.
# Values <= 1 are treated as a fraction.

TEXT_STATUS_EXTRACTORS = {"planning_status", "recharging_status"}
NUMERIC_CLASSES = {
    "battery",
    "voltage",
    "current",
    "temperature",
    "power",
    "signal_strength",
}
HEAD_TYPE_PATH = "HeadMsg.head_type"


# --------------------------------------------------------------------------
# Connecting
# --------------------------------------------------------------------------
def connect(username: str, password: str) -> tuple[YarboClient, list[Device]]:
    """Blocking: create a client, log in and fetch devices (run in executor)."""
    client = YarboClient()
    try:
        client.login(username, password)
        devices = [normalize_device(d) for d in client.get_devices()]
    except Exception:
        client.close()
        raise
    return client, devices


def normalize_device(device: Device) -> Device:
    """Map unknown REST type ids (e.g. "mower") onto a registry type.

    The SDK resolves control topics with an exact registry match, so an unknown
    type id would make every command fail.
    """
    device_type = get_device_type(device.type_id)
    if device_type is None or device_type.type_id == device.type_id:
        return device
    return replace(device, type_id=device_type.type_id)


def status_fields(type_id: str, entity_type: str) -> list[FieldDefinition]:
    """Status field definitions of one entity type for a device type."""
    device_type = get_device_type(type_id)
    if device_type is None:
        return []
    return [f for f in device_type.status_fields if f.entity_type == entity_type]


def control_fields(
    type_id: str, entity_type: str | None = None
) -> list[ControlFieldDefinition]:
    """Control field definitions (optionally of one entity type)."""
    device_type = get_device_type(type_id)
    if device_type is None:
        return []
    return [
        f
        for f in device_type.control_fields
        if entity_type is None or f.entity_type == entity_type
    ]


def control_topic_names(type_id: str) -> set[str]:
    """Names of all publishable command topics for a device type."""
    device_type = get_device_type(type_id)
    if device_type is None:
        return set()
    return {t.name for t in device_type.control_topics}


# --------------------------------------------------------------------------
# Generic value helpers
# --------------------------------------------------------------------------
def deep_merge(target: dict, source: dict) -> dict:
    """Merge ``source`` into ``target`` in place, recursing into dicts."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def unwrap_feedback(response: Any) -> dict:
    """Return the payload of a ``data_feedback`` response.

    Feedback looks like ``{"topic": ..., "state": 0, "data": {...}}``; a plain
    DeviceMSG-style dict is returned unchanged.
    """
    if not isinstance(response, dict):
        return {}
    if "topic" in response and isinstance(response.get("data"), dict):
        return response["data"]
    return response


def to_float(value: Any) -> float | None:
    """Best-effort float conversion."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def truthy(value: Any) -> bool | None:
    """Convert device flags (bool/int/"true") to bool; None stays None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes"}
    return bool(value)


def volume_percent(raw: Any) -> float | None:
    """Normalise a device volume to 0-100 (see ASSUMPTION above)."""
    value = to_float(raw)
    if value is None:
        return None
    if 0 <= value <= 1:
        value *= 100
    return round(min(max(value, 0.0), 100.0), 1)


# --------------------------------------------------------------------------
# Status extractors (named in the SDK registry as ``custom_extractor``)
# --------------------------------------------------------------------------
def _status_text(raw: Any, value_map: dict[str, str] | None) -> str | None:
    """Turn a plan/recharge status into one of the registry's display strings."""
    if raw is None:
        return None
    value_map = value_map or {}
    if isinstance(raw, str):
        text = raw.strip()
        if text in value_map:
            return value_map[text]
        match = re.search(r"\b(WP\d+|REC\d+)\b", text)
        if match:
            for display in value_map.values():
                if f"({match.group(1)})" in display:
                    return display
        return text
    if isinstance(raw, (dict, list)):
        return None
    return str(raw)


def _is_error_text(text: str | None) -> bool | None:
    if text is None:
        return None
    return text.startswith("Error") or bool(re.search(r"\b(WP|REC)\d+\b", text))


def _is_charging(data: dict) -> bool | None:
    value = to_float(extract_field(data, "BatteryMSG.status"))
    return None if value is None else value >= CHARGING_STATUS_MIN


def _ext_battery_capacity(data: dict, raw: Any, f: FieldDefinition) -> int | None:
    value = to_float(raw)
    return None if value is None else int(min(max(round(value), 0), 100))


def _ext_charging_threshold(data: dict, raw: Any, f: FieldDefinition) -> bool | None:
    return _is_charging(data)


def _ext_charging_power(data: dict, raw: Any, f: FieldDefinition) -> float | None:
    voltage = to_float(extract_field(data, "BatteryMSG.voltage"))
    current = to_float(extract_field(data, "BatteryMSG.current"))
    if voltage is None or current is None:
        return None
    if _is_charging(data) is False:
        return 0.0
    return round(abs(voltage * current), 1)


def _ext_network_priority(data: dict, raw: Any, f: FieldDefinition) -> str | None:
    return extract_active_network(raw if raw is not None else data.get("RoutePriority"))


def _ext_planning_status(data: dict, raw: Any, f: FieldDefinition) -> str | None:
    return _status_text(raw, f.value_map)


def _ext_planning_problem(data: dict, raw: Any, f: FieldDefinition) -> bool | None:
    return _is_error_text(_status_text(raw, f.value_map))


def _ext_recharging_status(data: dict, raw: Any, f: FieldDefinition) -> str | None:
    return _status_text(raw, f.value_map)


def _ext_nonzero(data: dict, raw: Any, f: FieldDefinition) -> bool | None:
    if raw is None:
        return None
    value = to_float(raw)
    return bool(raw) if value is None else value != 0


def _ext_positive(data: dict, raw: Any, f: FieldDefinition) -> bool | None:
    value = to_float(raw)
    return None if value is None else value > 0


def _ext_volume_scale(data: dict, raw: Any, f: FieldDefinition) -> float | None:
    return volume_percent(raw)


def _ext_rtk_signal(data: dict, raw: Any, f: FieldDefinition) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().title() in {"Strong", "Medium", "Weak"}:
        return raw.strip().title()
    value = to_float(raw)
    return None if value is None else RTK_QUALITY.get(int(value))


EXTRACTORS: dict[str, Callable[[dict, Any, FieldDefinition], Any]] = {
    "battery_capacity": _ext_battery_capacity,
    "charging_threshold": _ext_charging_threshold,
    "charging_power": _ext_charging_power,
    "network_priority": _ext_network_priority,
    "planning_status": _ext_planning_status,
    "planning_problem": _ext_planning_problem,
    "recharging_status": _ext_recharging_status,
    "nonzero_threshold": _ext_nonzero,
    "positive_threshold": _ext_positive,
    "volume_scale": _ext_volume_scale,
    "rtk_signal": _ext_rtk_signal,
}


def extract_status_value(fdef: FieldDefinition, data: dict) -> Any:
    """Compute the entity value of a status field from a merged device dict."""
    raw = extract_field(data, fdef.path)

    if fdef.custom_extractor:
        extractor = EXTRACTORS.get(fdef.custom_extractor)
        if extractor is not None:
            return extractor(data, raw, fdef)
        _LOGGER.debug("No extractor named %s; using raw value", fdef.custom_extractor)

    if raw is None:
        return None
    if fdef.entity_type == "binary_sensor":
        return truthy(raw)
    if fdef.value_map:
        return fdef.value_map.get(str(raw))
    if fdef.unit or fdef.device_class in NUMERIC_CLASSES:
        return to_float(raw)
    return raw


def sensor_options(fdef: FieldDefinition) -> list[str] | None:
    """Enum options for a sensor, or None when it must be a free-text sensor.

    Plan and recharge status have a display-string map, but raw values outside
    it would be rejected by an enum sensor, so they stay plain text.
    """
    if (
        fdef.entity_type == "sensor"
        and fdef.device_class == "enum"
        and fdef.value_map
        and fdef.custom_extractor not in TEXT_STATUS_EXTRACTORS
    ):
        return list(dict.fromkeys(fdef.value_map.values()))
    return None


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------
def head_type(data: dict) -> int | None:
    """Current attachment (HeadMsg.head_type) or None when unknown."""
    value = to_float(extract_field(data, HEAD_TYPE_PATH))
    return None if value is None else int(value)


def is_control_available(cf: ControlFieldDefinition, data: dict) -> bool:
    """Attachment-specific controls are only usable with a matching head."""
    if not cf.compatible_head_types:
        return True
    return head_type(data) in cf.compatible_head_types


def read_control_value(cf: ControlFieldDefinition, data: dict) -> Any:
    """Current value of a control entity, or None when the device doesn't report it."""
    raw = extract_field(data, cf.path)
    if cf.entity_type == "select":
        if raw is None:
            return None
        return (cf.state_value_map or {}).get(str(raw))
    if cf.entity_type == "switch":
        return truthy(raw)
    if cf.entity_type == "number":
        if cf.command_builder == "sound_volume":
            return volume_percent(raw)
        return to_float(raw)
    return None


def _current_volume_fraction(data: dict) -> float:
    percent = volume_percent(extract_field(data, "StateMSG.volume"))
    return 0.7 if percent is None else round(percent / 100, 2)


def _current_sound_enabled(data: dict) -> bool:
    enabled = truthy(extract_field(data, "StateMSG.enable_sound"))
    return True if enabled is None else enabled


def _flag(value: Any) -> int:
    return 1 if value else 0


COMMAND_BUILDERS: dict[str, Callable[[Any, dict], dict[str, Any]]] = {
    "sound_switch": lambda v, d: {
        "enable": bool(v),
        "vol": _current_volume_fraction(d),
        "mode": 0,
    },
    "sound_volume": lambda v, d: {
        "enable": _current_sound_enabled(d),
        "vol": round(min(max(float(v), 0.0), 100.0) / 100, 2),
        "mode": 0,
    },
    "light_switch": lambda v, d: {"led_head": _flag(v)},
    "person_detection_switch": lambda v, d: {"state": _flag(v)},
    "state_int_switch": lambda v, d: {"state": _flag(v)},
    "state_bool_switch": lambda v, d: {"state": bool(v)},
    "geo_fence_switch": lambda v, d: {"id": 1, "enable_elec_fence": bool(v)},
    "ignore_obstacles_switch": lambda v, d: {"switch": _flag(v)},
    "ignore_obstacle_zones": lambda v, d: {"zone": []},
    "play_sound": lambda v, d: {"song_name": "find yarbo"},
    "empty_payload": lambda v, d: {},
}


def build_command(
    cf: ControlFieldDefinition, value: Any, data: dict
) -> tuple[str, dict[str, Any]]:
    """Return ``(command_topic_name, payload)`` for a control entity action."""
    if cf.command_builder:
        builder = COMMAND_BUILDERS.get(cf.command_builder)
        if builder is None:
            raise ValueError(f"Unknown command builder: {cf.command_builder}")
        payload = builder(value, data)
    elif cf.command_key is None:
        raise ValueError(f"Control {cf.name} has no command_key or command_builder")
    elif cf.entity_type == "select":
        payload = {cf.command_key: (cf.value_map or {})[value]}
    else:
        number = float(value)
        payload = {cf.command_key: int(number) if number.is_integer() else number}
    payload.update(cf.extra_payload or {})
    return cf.command_topic, payload


# --------------------------------------------------------------------------
# Lawn mower activity
# --------------------------------------------------------------------------
_NOT_PAUSED = {"", "0", "none", "false", "not paused", "not started", "normal"}


def is_paused(raw: Any) -> bool:
    """ASSUMPTION: StateMSG.planning_paused is empty/0/"Not Paused" when running."""
    if raw is None:
        return False
    return str(raw).strip().lower() not in _NOT_PAUSED


def mower_activity(data: dict) -> str | None:
    """One of error/returning/mowing/docked/paused, or None when no data yet."""
    working = to_float(extract_field(data, "StateMSG.working_state"))
    if working is None:
        working = to_float(extract_field(data, "HeartBeatMSG.working_state"))
    if working is None and not data:
        return None

    error = to_float(extract_field(data, "StateMSG.error_code"))
    if error is not None and error != 0:
        return "error"

    recharge = _status_text(
        extract_field(data, "StateMSG.on_going_recharging"), None
    )
    if recharge and (
        recharge.startswith("Returning") or recharge == "Repositioning"
    ):
        return "returning"
    if working == 1:
        return "mowing"
    if _is_charging(data):
        return "docked"
    return "paused"


# --------------------------------------------------------------------------
# Optimistic state
# --------------------------------------------------------------------------
class Optimistic:
    """Holds a just-commanded value until the device confirms it (or it times out)."""

    TTL = 15.0

    def __init__(self) -> None:
        self._value: Any = None
        self._until = 0.0

    def set(self, value: Any) -> None:
        self._value = value
        self._until = time.monotonic() + self.TTL

    def resolve(self, actual: Any) -> Any:
        """Return what the entity should report."""
        if self._value is None:
            return actual
        if actual is not None and actual == self._value:
            self._value = None
            return actual
        if time.monotonic() < self._until:
            return self._value
        if actual is None:  # device never reports this value: assumed state
            return self._value
        self._value = None
        return actual
