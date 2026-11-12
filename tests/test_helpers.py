"""Tests for the Home Assistant-independent logic (needs only yarbo-data-sdk).

Run: pytest tests   (helpers.py is loaded directly, without Home Assistant)
"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "yarbo_helpers",
    Path(__file__).parent.parent / "custom_components" / "yarbo" / "helpers.py",
)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

TYPE = "yarbo_Y"


def sf(name, entity_type):
    return next(f for f in h.status_fields(TYPE, entity_type) if f.name == name)


def cf(name):
    return next(c for c in h.control_fields(TYPE) if c.name == name)


DATA = {
    "BatteryMSG": {"capacity": 85.4, "status": 1, "voltage": 50.0, "current": -4.0},
    "StateMSG": {
        "working_state": 0, "error_code": 0, "stuck": 0, "volume": 0.5,
        "enable_sound": True, "on_going_planning": "Error: Plan Not Found (WP003)",
    },
    "HeadMsg": {"head_type": 3},
    "route_priority": {"hg0": -1, "wlan0": 1, "wwan0": 2},
    "LedInfoMSG": {"led_head": 1},
    "RTKMSG": {"status": 4},
}


def test_every_extractor_and_builder_in_registry_is_implemented():
    fields = h.status_fields(TYPE, "sensor") + h.status_fields(TYPE, "binary_sensor")
    for f in fields:
        if f.custom_extractor:
            assert f.custom_extractor in h.EXTRACTORS, f.custom_extractor
    for c in h.control_fields(TYPE):
        if c.command_builder:
            assert c.command_builder in h.COMMAND_BUILDERS, c.command_builder


def test_unknown_type_falls_back_and_is_normalised():
    from yarbo_robot_sdk.models import Device
    d = h.normalize_device(Device("S", "mower", "n", "m", True))
    assert d.type_id == TYPE


@pytest.mark.parametrize("name,expected", [
    ("Battery", 85), ("Network", "Wifi"), ("Activity", "standby"),
    ("Head Type", "Mower"), ("RTK Signal", "Strong"), ("Charging Power", 200.0),
])
def test_sensor_values(name, expected):
    assert h.extract_status_value(sf(name, "sensor"), DATA) == expected


def test_binary_sensors():
    assert h.extract_status_value(sf("Charging", "binary_sensor"), DATA) is True
    assert h.extract_status_value(sf("Stuck", "binary_sensor"), DATA) is False
    assert h.extract_status_value(sf("Problem", "binary_sensor"), DATA) is True


def test_plan_status_maps_code_to_display_string():
    f = sf("Auto Plan Status", "sensor")
    assert h.extract_status_value(f, DATA).endswith("(WP003)")
    assert h.sensor_options(f) is None  # free text, not enum
    assert h.sensor_options(sf("Head Type", "sensor"))[0] == "None"


def test_missing_data_is_none_not_error():
    for f in h.status_fields(TYPE, "sensor") + h.status_fields(TYPE, "binary_sensor"):
        h.extract_status_value(f, {})


def test_volume_scale_and_commands():
    assert h.volume_percent(0.5) == 50.0 and h.volume_percent(66.7) == 66.7
    assert h.build_command(cf("Volume"), 30, DATA) == (
        "set_sound_param", {"enable": True, "vol": 0.3, "mode": 0})
    assert h.build_command(cf("Sound Switch"), False, DATA)[1] == {
        "enable": False, "vol": 0.5, "mode": 0}
    assert h.build_command(cf("Head Light"), True, {}) == ("light_ctrl", {"led_head": 1})
    assert h.build_command(cf("Working State"), "working", {}) == (
        "set_working_state", {"state": 1, "source": "smart_home"})
    assert h.build_command(cf("Blade Height"), 60.0, {}) == ("mower_target_cmd", {"target": 60})
    assert h.build_command(cf("Geo Fence"), True, {})[1] == {"id": 1, "enable_elec_fence": True}
    assert h.build_command(cf("Child Lock"), True, {})[1] == {"state": True}
    assert h.build_command(cf("Emergency Stop"), None, {}) == ("stop", {})
    assert h.build_command(cf("Ignore Obstacle Zones"), None, {})[1] == {"zone": []}


def test_every_command_topic_exists_in_registry():
    topics = h.control_topic_names(TYPE)
    for c in h.control_fields(TYPE):
        assert c.command_topic in topics


def test_head_gating():
    assert h.is_control_available(cf("Blade Height"), DATA)
    assert not h.is_control_available(cf("Chute Angle"), DATA)
    assert not h.is_control_available(cf("Blade Height"), {})
    assert h.is_control_available(cf("Head Light"), {})


def test_deep_merge_keeps_heartbeat_and_partial_dicts():
    base = {"HeartBeatMSG": {"working_state": 1}, "StateMSG": {"a": 1, "b": 2}}
    h.deep_merge(base, {"StateMSG": {"b": 3}, "BatteryMSG": {"capacity": 80}})
    assert base["HeartBeatMSG"] == {"working_state": 1}
    assert base["StateMSG"] == {"a": 1, "b": 3}


def test_unwrap_feedback():
    assert h.unwrap_feedback({"topic": "get_device_msg", "state": 0, "data": {"x": 1}}) == {"x": 1}
    assert h.unwrap_feedback({"BatteryMSG": {}}) == {"BatteryMSG": {}}


def test_mower_activity():
    assert h.mower_activity({}) is None
    assert h.mower_activity({"StateMSG": {"working_state": 1}}) == "mowing"
    assert h.mower_activity({"StateMSG": {"working_state": 1, "error_code": 5}}) == "error"
    assert h.mower_activity({"StateMSG": {"working_state": 0},
                             "BatteryMSG": {"status": 1}}) == "docked"
    assert h.mower_activity({"StateMSG": {"working_state": 0,
                             "on_going_recharging": "Returning on Path"}}) == "returning"
    assert h.mower_activity({"HeartBeatMSG": {"working_state": 0}}) == "paused"


def test_optimistic():
    o = h.Optimistic()
    assert o.resolve(False) is False
    o.set(True)
    assert o.resolve(False) is True      # device hasn't caught up yet
    assert o.resolve(True) is True       # confirmed -> cleared
    assert o.resolve(False) is False
    o.set(True)
    assert o.resolve(None) is True       # never reported: assumed
