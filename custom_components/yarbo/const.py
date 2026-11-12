"""Constants for the Yarbo integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "yarbo"
MANUFACTURER: Final = "Yarbo"

# How long without any MQTT message before we stop trusting "recently seen".
ONLINE_TIMEOUT: Final = 120.0
# Housekeeping tick: refresh the REST device list (online flag), retry GPS
# reference, and re-request a snapshot from quiet devices.
TICK_INTERVAL: Final = timedelta(seconds=60)
# If a device that REST says is online has been silent this long, ask for a snapshot.
STALE_AFTER: Final = 300.0
# DeviceMSG can arrive several times a second; coalesce entity updates.
NOTIFY_INTERVAL: Final = 1.0

SERVICE_START_PLAN: Final = "start_plan"
SERVICE_SEND_COMMAND: Final = "send_command"

# Display-name tweaks (the SDK has two different things called "Problem", etc.)
NAME_OVERRIDES: Final = {
    "Problem": "Auto Plan Problem",
}

# Status fields that are better shown as diagnostic entities.
DIAGNOSTIC_PATHS: Final = {
    "HeadAndVersionCheck.head_firmware_version",
    "BodyVersionMsg.body_fw_version",
    "HeadSerialMsg.head_sn",
    "WifiInfo.signal",
    "net_module_status.lte_rssi",
    "halow_status.strength",
    "route_priority",
    "RTKMSG.sat_num",
    "RunningStatusMSG.rain_sensor_data",
    "__computed__.charging_power",
    "BatteryMSG.voltage",
    "BatteryMSG.current",
    "CombinedOdom.x",
    "CombinedOdom.y",
    "CombinedOdom.phi",
}
DIAGNOSTIC_PREFIXES: Final = ("BatteryMSG.temperature",)

# Control fields that are configuration rather than day-to-day controls.
CONFIG_CONTROL_PATHS: Final = {
    "enable_elec_fence",
    "map_obstacle_switch",
    "__action__.ignore_obstacle_zones",
    "StateMSG.person_detect_status",
    "StateMSG.robot_follow_state",
}
