# Yarbo for Home Assistant

Custom integration (HACS) for [Yarbo](https://www.yarbo.com) robots, built on Yarbo's
official [YarboDataSDK](https://github.com/YarboInc/YarboDataSDK) (`yarbo-data-sdk`).

Cloud, push-based: sign in with your Yarbo app email and password; live status arrives
over MQTT, so there is no polling.

## Install

1. Replace `YOUR_GITHUB_USER` in `custom_components/yarbo/manifest.json` and publish this
   repo to GitHub.
2. HACS -> Integrations -> ⋮ -> **Custom repositories** -> add the repo URL, category *Integration*.
3. Install **Yarbo**, restart Home Assistant.
4. Settings -> Devices & services -> **Add integration** -> *Yarbo*.

Requires Home Assistant 2024.11 or newer.

## Entities (per robot)

Most are generated from the SDK's device registry, so new fields in a future SDK release
appear without code changes.

| Platform | What you get |
|---|---|
| `lawn_mower` | Main control: start (resume if paused, otherwise run the selected plan), pause, dock. Works with any attachment. |
| `sensor` | Battery, health, voltage/current/cell temps, charging power, activity, error code, plan / recharge / pause status, Wi-Fi / 4G / HaLow RSSI, active network, head type, firmware versions, RTK signal, ambient temperature, position X/Y/heading |
| `binary_sensor` | Online, charging, battery temp error, stuck, obstacle, plan problem, rain |
| `switch` | Sound, head light, child lock, person detection, follow mode, geo fence, ignore obstacles |
| `number` | Volume; blade height / blade speed (mower heads); chute angle (snow blower head) |
| `select` | Working state (standby/working); **Plan** (which automatic plan *Start* runs) |
| `button` | Play sound, emergency stop, ignore obstacle zones, refresh plans |
| `device_tracker` | GPS location from local odometry + the robot's GPS reference origin |

Attachment-specific controls show as unavailable unless the matching head is fitted.
Many diagnostic and rarely-used entities are disabled by default; enable them from the
entity list. A read-only sensor is not created where a control entity already shows the
same value (head light, volume, person detection, follow mode, sound).

## Services

* `yarbo.start_plan` - `plan_id`, optional `start_percent`.
* `yarbo.send_command` - publish any command topic known to the SDK registry
  (e.g. `wireless_charging_cmd` with `{"cmd": 1}`). Some commands change safety settings.

## Things to verify against your robot

The SDK's registry names some value conversions without defining them. These were
implemented from the docs and tests and are the first places to look if a value seems off
(all in `helpers.py`, marked `ASSUMPTION`):

* **Charging** = `BatteryMSG.status >= 1`.
* **Volume**: `StateMSG.volume` values <= 1 are treated as a 0-1 fraction, otherwise as 0-100.
* **RTK Signal** numeric codes follow NMEA fix quality (4 = Strong, 5 = Medium, 1/2 = Weak).
* **Paused** detection from `StateMSG.planning_paused` (empty / 0 / "Not Paused" = running).
* **Auto Plan / Recharging status** are plain-text sensors: if the robot reports a code the
  SDK doesn't list, you see the raw value.
* **Heading** is shown as reported (may be radians despite the SDK's "°" unit).
* Geo fence / ignore obstacles are not reported back by the robot, so those switches use
  assumed state.

Use *Download diagnostics* on the integration to share a redacted snapshot if something
doesn't match.

## Development

```
pip install yarbo-data-sdk
pytest tests        # pure-logic tests, no Home Assistant needed
```

## License

The SDK is licensed **PolyForm Noncommercial 1.0.0**: free for noncommercial use, but it
does not grant commercial rights. Check its [license](https://github.com/YarboInc/YarboDataSDK/blob/main/LICENSE)
before bundling or selling anything built on it. Add your own license for this repo's code.
