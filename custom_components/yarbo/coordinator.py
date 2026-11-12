"""Push-based coordinator for the Yarbo integration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from yarbo_robot_sdk import YarboClient
from yarbo_robot_sdk.device_helpers import convert_local_to_gps
from yarbo_robot_sdk.exceptions import (
    AuthenticationError,
    TokenExpiredError,
    YarboSDKError,
)
from yarbo_robot_sdk.models import ControlFieldDefinition, Device

from .const import (
    DOMAIN,
    NOTIFY_INTERVAL,
    ONLINE_TIMEOUT,
    STALE_AFTER,
    TICK_INTERVAL,
)
from .helpers import build_command, deep_merge, to_float, unwrap_feedback

_LOGGER = logging.getLogger(__name__)

type YarboConfigEntry = ConfigEntry[YarboCoordinator]


class YarboCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Receives MQTT pushes for every robot on the account.

    ``data`` maps serial number -> merged device dict (DeviceMSG fields plus
    the heartbeat stored under ``HeartBeatMSG``).
    """

    config_entry: YarboConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: YarboConfigEntry,
        client: YarboClient,
        devices: list[Device],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,  # push only
        )
        self.client = client
        self.devices: dict[str, Device] = {d.sn: d for d in devices}
        self.data = {sn: {} for sn in self.devices}
        self.gps_ref: dict[str, tuple[float, float]] = {}
        self.plans: dict[str, list[dict[str, Any]]] = {}
        self.selected_plan: dict[str, int | None] = {}
        self._last_seen: dict[str, float] = {}
        self._flush_handle: asyncio.TimerHandle | None = None
        self._unsub_tick = None
        self._tick_running = False
        self._stopped = False

    # ------------------------------------------------------------------ start/stop
    async def async_start(self) -> None:
        """Subscribe to every device and fetch an initial snapshot."""
        for device in self.devices.values():
            try:
                await self.hass.async_add_executor_job(self._subscribe, device)
            except TokenExpiredError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except YarboSDKError as err:
                raise ConfigEntryNotReady(
                    f"Could not subscribe to {device.sn}: {err}"
                ) from err

        await asyncio.gather(*(self._async_fetch_snapshot(sn) for sn in self.devices))
        self.config_entry.async_create_background_task(
            self.hass, self._async_fetch_static_all(), f"{DOMAIN}_static_data"
        )
        self._unsub_tick = async_track_time_interval(
            self.hass, self._async_tick, TICK_INTERVAL
        )

    async def async_stop(self) -> None:
        """Stop timers, MQTT and background work."""
        self._stopped = True
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        if self._flush_handle:
            self._flush_handle.cancel()
            self._flush_handle = None
        await self.async_shutdown()
        await self.hass.async_add_executor_job(self.client.close)

    def _subscribe(self, device: Device) -> None:
        """Blocking (executor). Order matters: feedback channel first."""
        bound = self.client.device(device)
        bound.core.subscribe_data_feedback()
        bound.core.subscribe_device_message(partial(self._mqtt_device, device.sn))
        bound.core.subscribe_heart_beat(partial(self._mqtt_heartbeat, device.sn))

    # ------------------------------------------------------------------ MQTT thread
    def _mqtt_device(self, sn: str, topic: str, data: dict) -> None:
        self.hass.loop.call_soon_threadsafe(self._handle_message, sn, False, data)

    def _mqtt_heartbeat(self, sn: str, topic: str, data: dict) -> None:
        self.hass.loop.call_soon_threadsafe(self._handle_message, sn, True, data)

    # ------------------------------------------------------------------ event loop
    @callback
    def _handle_message(self, sn: str, heartbeat: bool, data: dict) -> None:
        if self._stopped or not isinstance(data, dict) or "_raw" in data:
            return
        if heartbeat:
            data = {"HeartBeatMSG": data}
        # Merge, never replace: a DeviceMSG must not wipe the heartbeat.
        deep_merge(self.data.setdefault(sn, {}), data)
        self._last_seen[sn] = time.monotonic()
        self._schedule_notify()

    @callback
    def _schedule_notify(self) -> None:
        if self._flush_handle is None and not self._stopped:
            self._flush_handle = self.hass.loop.call_later(
                NOTIFY_INTERVAL, self._flush
            )

    @callback
    def _flush(self) -> None:
        self._flush_handle = None
        if not self._stopped:
            self.async_set_updated_data(self.data)

    def is_online(self, sn: str) -> bool:
        """Recent MQTT traffic wins; otherwise trust the REST online flag."""
        seen = self._last_seen.get(sn)
        if seen is not None and time.monotonic() - seen < ONLINE_TIMEOUT:
            return True
        return self.devices[sn].online

    # ------------------------------------------------------------------ data fetch
    async def _async_fetch_snapshot(self, sn: str) -> None:
        device = self.devices[sn]
        try:
            response = await self.hass.async_add_executor_job(
                partial(
                    self.client.get_device_msg, device.sn, device.type_id, timeout=10.0
                )
            )
        except (TimeoutError, YarboSDKError) as err:
            _LOGGER.debug("No initial snapshot from %s: %s", sn, err)
            return
        self._handle_message(sn, False, unwrap_feedback(response))

    async def _async_fetch_static_all(self) -> None:
        await asyncio.gather(
            *(self._async_fetch_static(sn) for sn in self.devices),
            return_exceptions=True,
        )

    async def _async_fetch_static(self, sn: str) -> None:
        await self.async_fetch_gps_ref(sn)
        await self.async_refresh_plans(sn)

    async def async_fetch_gps_ref(self, sn: str) -> None:
        """Fetch the GPS reference origin used to place the robot on a map."""
        device = self.devices[sn]
        try:
            response = await self.hass.async_add_executor_job(
                partial(self.client.read_gps_ref, device.sn, device.type_id, timeout=10.0)
            )
        except (TimeoutError, YarboSDKError) as err:
            _LOGGER.debug("No GPS reference from %s: %s", sn, err)
            return
        ref = unwrap_feedback(response).get("ref")
        if isinstance(ref, dict):
            lat, lon = to_float(ref.get("latitude")), to_float(ref.get("longitude"))
            if lat and lon:  # (0, 0) means "not set"
                self.gps_ref[sn] = (lat, lon)
                self._schedule_notify()

    async def async_refresh_plans(self, sn: str) -> None:
        """Fetch the automatic plans configured on the robot."""
        device = self.devices[sn]
        try:
            response = await self.hass.async_add_executor_job(
                partial(
                    self.client.read_all_plan, device.sn, device.type_id, timeout=10.0
                )
            )
        except (TimeoutError, YarboSDKError) as err:
            _LOGGER.debug("No plans from %s: %s", sn, err)
            return
        raw = unwrap_feedback(response).get("data")
        if not isinstance(raw, list):
            return
        plans = [
            {"id": int(p["id"]), "name": str(p.get("name") or f"Plan {p['id']}")}
            for p in raw
            if isinstance(p, dict) and to_float(p.get("id")) is not None
        ]
        self.plans[sn] = plans
        if self.selected_plan.get(sn) not in {p["id"] for p in plans}:
            self.selected_plan[sn] = None
        self._schedule_notify()

    def plan_labels(self, sn: str) -> dict[str, int]:
        """Select-friendly ``label -> plan id`` (names disambiguated by id)."""
        plans = self.plans.get(sn, [])
        names = [p["name"] for p in plans]
        return {
            (p["name"] if names.count(p["name"]) == 1 else f"{p['name']} (#{p['id']})"): p["id"]
            for p in plans
        }

    def resolve_plan_id(self, sn: str) -> int | None:
        """Selected plan, or the only plan if there is exactly one."""
        if (selected := self.selected_plan.get(sn)) is not None:
            return selected
        plans = self.plans.get(sn, [])
        return plans[0]["id"] if len(plans) == 1 else None

    def device_location(self, sn: str) -> tuple[float, float] | None:
        """Robot position as (lat, lon) from local odometry and the GPS reference."""
        ref = self.gps_ref.get(sn)
        odom = self.data.get(sn, {}).get("CombinedOdom")
        if ref is None or not isinstance(odom, dict):
            return None
        x, y = to_float(odom.get("x")), to_float(odom.get("y"))
        if x is None or y is None:
            return None
        return convert_local_to_gps(ref[0], ref[1], x, y)

    # ------------------------------------------------------------------ housekeeping
    async def _async_tick(self, _now: datetime) -> None:
        if self._tick_running or self._stopped:
            return
        self._tick_running = True
        try:
            await self._async_refresh_devices()
            now = time.monotonic()
            for sn, device in self.devices.items():
                if sn not in self.gps_ref and device.online:
                    self.config_entry.async_create_background_task(
                        self.hass, self.async_fetch_gps_ref(sn), f"{DOMAIN}_gps_{sn}"
                    )
                seen = self._last_seen.get(sn)
                if device.online and (seen is None or now - seen > STALE_AFTER):
                    await self._async_fetch_snapshot(sn)
            self.async_set_updated_data(self.data)  # re-evaluate online state
        finally:
            self._tick_running = False

    async def _async_refresh_devices(self) -> None:
        try:
            fresh = await self.hass.async_add_executor_job(self.client.get_devices)
        except TokenExpiredError:
            await self._async_relogin()
        except AuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
        except YarboSDKError as err:
            _LOGGER.debug("Device list refresh failed: %s", err)
        else:
            for device in fresh:
                if device.sn in self.devices:
                    self.devices[device.sn].online = device.online

    async def _async_relogin(self) -> None:
        """Refresh token expired: log in again with the stored credentials."""
        try:
            await self.hass.async_add_executor_job(
                self.client.login,
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
        except AuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
        except YarboSDKError as err:
            _LOGGER.debug("Re-login failed: %s", err)

    # ------------------------------------------------------------------ commands
    async def async_send_command(
        self, sn: str, command: str, payload: dict[str, Any]
    ) -> None:
        """Publish a command to the robot."""
        device = self.devices[sn]
        try:
            await self.hass.async_add_executor_job(
                self.client.mqtt_publish_command,
                device.sn,
                device.type_id,
                command,
                payload,
            )
        except YarboSDKError as err:
            raise HomeAssistantError(f"Yarbo command '{command}' failed: {err}") from err

    async def async_send_control(
        self, sn: str, cf: ControlFieldDefinition, value: Any = None
    ) -> None:
        """Build and publish the command for a registry control field."""
        command, payload = build_command(cf, value, self.data.get(sn, {}))
        await self.async_send_command(sn, command, payload)
