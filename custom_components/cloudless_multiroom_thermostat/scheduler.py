"""The heating scheduler (#114, #115): runs the room schedules in the integration.

Each room is in one of five schedule states:

- active: the room follows its week schedule; a target or preset set by hand
  (service call, card, HA's own thermostat card) is an override until the
  next schedule change;
- none: the room has no schedule and holds the Temperature without schedule
  (15 °C by default); target and preset calls are refused;
- off: scheduling off, the room is the user's (presets and targets as in v1);
- suspended: schedules are suspended for the whole system; rooms with a
  schedule hold the Temperature without schedule. A change by hand takes that
  one room out of the suspend: it follows its schedule again, with the change
  on top, until schedules are resumed (or suspended again);
- blocked: the schedule file can't be used (newer version, broken); which
  rooms had scheduling off can't be known, so every room holds the
  Temperature without schedule.

Hvac mode is never touched: off is off, whatever the schedule says, and
turning heat back on picks up what the schedule says now. The scheduler only
sets the room's target and preset; away, windows and pauses still work on
top, as in v1.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NO_SCHEDULE_TEMP,
    DEFAULT_NO_SCHEDULE_TEMP,
    DOMAIN,
    SCHEDULE_ACTIVE,
    SCHEDULE_BLOCKED,
    SCHEDULE_NONE,
    SCHEDULE_OFF,
    SCHEDULE_SUSPENDED,
)
from .schedule import (
    PRESET_OFF,
    SCHEDULING_OFF,
    SCHEDULING_ON,
    ScheduleError,
    current_point,
    next_change,
    preset_ids,
    preset_temperature,
    validate_week,
)

if TYPE_CHECKING:
    from .controller import HeatingController, Room

_LOGGER = logging.getLogger(__name__)


def issue_ids(entry_id: str) -> tuple[str, str]:
    """Repairs issues of one heating system: rooms without schedule, file blocked."""
    return f"no_schedule_{entry_id}", f"schedules_blocked_{entry_id}"


def _refuse(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders or None
    )


class Scheduler:
    """Applies schedules and overrides to the rooms of one heating system."""

    def __init__(self, hass: HomeAssistant, controller: HeatingController) -> None:
        self.hass = hass
        self.controller = controller
        self._timer: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------- reading
    @property
    def store(self):
        return self.controller.schedules

    @property
    def data(self) -> dict[str, Any] | None:
        store = self.store
        return None if store is None else store.data

    @property
    def no_schedule_temp(self) -> float:
        return float(self.controller.settings.get(CONF_NO_SCHEDULE_TEMP, DEFAULT_NO_SCHEDULE_TEMP))

    @property
    def tz(self):
        return dt_util.get_time_zone(self.hass.config.time_zone)

    def state(self, room: Room) -> str:
        data = self.data
        if data is None:
            return SCHEDULE_BLOCKED
        entry = data["rooms"].get(room.room_id)
        if entry is None:
            return SCHEDULE_NONE
        if entry["scheduling"] == SCHEDULING_OFF:
            return SCHEDULE_OFF
        if data["suspended"] and room.room_id not in data["unsuspended"]:
            return SCHEDULE_SUSPENDED
        return SCHEDULE_ACTIVE

    def preset_ids(self) -> list[str]:
        data = self.data
        return preset_ids(data) if data is not None else ["eco", "warm"]

    def preset_temp(self, room: Room, preset: str) -> float:
        """The room's temperature for a preset; Off and not used give the off temperature."""
        data = self.data
        if data is None:
            temp = {"eco": room.eco_temp, "warm": room.warm_temp}.get(preset)
        else:
            temp = preset_temperature(data, room.room_id, preset)
        return self.controller.off_temp if temp is None else temp

    def override(self, room: Room, now: datetime | None = None) -> dict[str, Any] | None:
        data = self.data
        if data is None or self.state(room) != SCHEDULE_ACTIVE:
            return None
        found = data["overrides"].get(room.room_id)
        if not found:
            return None
        until = found.get("until")
        if until is not None and dt_util.parse_datetime(until) <= (now or dt_util.utcnow()):
            return None
        return found

    def next_change(self, room: Room, now: datetime | None = None) -> tuple[datetime, str] | None:
        if self.state(room) != SCHEDULE_ACTIVE:
            return None
        found = next_change(self.data["rooms"][room.room_id]["week"], now or dt_util.utcnow(), self.tz)
        return None if found is None else (found[0], found[1]["preset"])

    def attributes(self, room: Room) -> dict[str, Any]:
        """For the card: schedule state, next change and override."""
        change = self.next_change(room)
        override = self.override(room)
        return {
            "schedule_state": self.state(room),
            "next_change": None
            if change is None
            else {"at": dt_util.as_local(change[0]).isoformat(), "preset": change[1]},
            "override_until": None
            if override is None or override.get("until") is None
            else dt_util.as_local(dt_util.parse_datetime(override["until"])).isoformat(),
        }

    # ------------------------------------------------------------ applying
    @callback
    def async_start(self) -> None:
        self.apply()

    @callback
    def async_stop(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    @callback
    def apply(self) -> None:
        """Set every scheduled room's target and preset for now, then wait for the next change."""
        now = dt_util.utcnow()
        self._drop_expired(now)
        for room in self.controller.rooms.values():
            state = self.state(room)
            if state == SCHEDULE_OFF:
                continue
            if state == SCHEDULE_ACTIVE:
                override = self.override(room, now)
                if override is not None:
                    room.target, room.preset = float(override["target"]), override.get("preset")
                    continue
                point = current_point(self.data["rooms"][room.room_id]["week"], now, self.tz)
                room.preset = point["preset"]
                room.target = self.preset_temp(room, point["preset"])
            else:
                room.target, room.preset = self.no_schedule_temp, None
        self._update_repairs()
        self._arm(now)
        self.controller.request_recompute()

    def _drop_expired(self, now: datetime) -> None:
        data = self.data
        if data is None:
            return
        expired = [
            rid for rid, o in data["overrides"].items()
            if o.get("until") is not None and dt_util.parse_datetime(o["until"]) <= now
        ]
        for rid in expired:
            del data["overrides"][rid]
        if expired:
            self.store.async_delay_save()

    def _arm(self, now: datetime) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None
        moments: list[datetime] = []
        for room in self.controller.rooms.values():
            change = self.next_change(room, now)
            if change is not None:
                moments.append(change[0])
            override = self.override(room, now)
            if override is not None and override.get("until") is not None:
                moments.append(dt_util.parse_datetime(override["until"]))
        if moments:
            self._timer = async_track_point_in_utc_time(self.hass, self._on_timer, min(moments))

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._timer = None
        self.apply()

    def _update_repairs(self) -> None:
        entry = self.controller.entry
        no_schedule, blocked = issue_ids(entry.entry_id)
        if self.store is not None and self.store.blocked is not None:
            ir.async_create_issue(
                self.hass, DOMAIN, blocked, is_fixable=False, severity=ir.IssueSeverity.ERROR,
                translation_key="schedules_blocked",
                translation_placeholders={"system": entry.title, "reason": self.store.blocked},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, blocked)
        missing = sorted(r.name for r in self.controller.rooms.values() if self.state(r) == SCHEDULE_NONE)
        if missing:
            ir.async_create_issue(
                self.hass, DOMAIN, no_schedule, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="rooms_without_schedule",
                translation_placeholders={
                    "system": entry.title,
                    "rooms": ", ".join(missing),
                    "temperature": f"{self.no_schedule_temp:g}",
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, no_schedule)

    # ------------------------------------------------------- user requests
    def _check_can_change(self, room: Room) -> str:
        state = self.state(room)
        if state == SCHEDULE_NONE:
            raise _refuse("no_schedule", room=room.name)
        if state == SCHEDULE_BLOCKED:
            raise _refuse("schedules_blocked", room=room.name)
        if state == SCHEDULE_SUSPENDED:
            # A change by hand starts this room's schedule again (decided 2026-11-23)
            self.data["unsuspended"].append(room.room_id)
            return SCHEDULE_ACTIVE
        return state

    async def async_request_target(self, room: Room, target: float) -> None:
        """A target set by hand: v1 with scheduling off, else an override until the next change."""
        if self._check_can_change(room) == SCHEDULE_OFF:
            self.controller.set_room_state(room.room_id, target=target, preset=None)
            return
        await self._async_set_override(room, target, None)

    async def async_request_preset(self, room: Room, preset: str | None) -> None:
        """A preset chosen by hand; none on a scheduled room goes back to the schedule."""
        state = self._check_can_change(room)
        if preset is not None and preset != PRESET_OFF and preset not in self.preset_ids():
            raise _refuse("unknown_preset", preset=preset)
        if state == SCHEDULE_OFF:
            if preset is None:
                self.controller.set_room_state(room.room_id, preset=None)
            else:
                self.controller.set_room_state(room.room_id, target=self.preset_temp(room, preset), preset=preset)
            return
        if preset is None:
            await self.async_resume(room)
            return
        await self._async_set_override(room, self.preset_temp(room, preset), preset)

    async def _async_set_override(self, room: Room, target: float, preset: str | None) -> None:
        change = self.next_change(room)
        self.data["overrides"][room.room_id] = {
            "target": target,
            "preset": preset,
            "until": None if change is None else change[0].isoformat(),
            "keep_away": False,
        }
        await self.store.async_save()
        self.apply()

    async def async_resume(self, room: Room) -> None:
        """Back to schedule: drop the room's override."""
        if self.data is not None and self.data["overrides"].pop(room.room_id, None) is not None:
            await self.store.async_save()
        self.apply()

    async def async_set_schedule(
        self, room: Room, week: list[Any] | None, scheduling: str = SCHEDULING_ON
    ) -> None:
        data = self.data
        if data is None:
            raise _refuse("schedules_blocked", room=room.name)
        current = data["rooms"].get(room.room_id) or {}
        if week is not None:
            try:
                week = validate_week(week, preset_ids(data))
            except ScheduleError as err:
                raise ServiceValidationError(str(err)) from err
        else:
            week = current.get("week")
        if scheduling == SCHEDULING_ON and week is None:
            raise _refuse("no_week", room=room.name)
        data["rooms"][room.room_id] = {"scheduling": scheduling, "week": week}
        data["overrides"].pop(room.room_id, None)
        await self.store.async_save()
        self.apply()

    async def async_suspend(self, suspended: bool) -> None:
        data = self.data
        if data is None:
            raise _refuse("schedules_blocked", room=self.controller.entry.title)
        if data["suspended"] != suspended or data["unsuspended"]:
            data["suspended"] = suspended
            data["unsuspended"] = []
            await self.store.async_save()
        self.apply()
