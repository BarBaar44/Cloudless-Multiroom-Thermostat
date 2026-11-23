"""Schedule data model for v2.0.0 (#112, #113): presets, week schedules, overrides.

Pure functions on plain dicts, no Home Assistant imports, so the rules can be
tested on their own. `schedule_store.py` keeps the data in an HA Store.

Layout of the data (schema version 1):

    {
      "presets": [{"id": "eco", "name": "Eco", "builtin": true}, ...],
      "temperatures": {room_id: {preset_id: 15.0 | None}},   # None: not used
      "rooms": {room_id: {"scheduling": "on" | "off", "week": [[point, ...] x 7]}},
      "overrides": {room_id: {...}},
      "suspended": false,
      "unsuspended": [room_id, ...],   # taken out of the suspend by a change by hand
      "guest": None | {"until": iso | None},  # someone is home, whatever presence says
      "sun": {room_id: {"point": iso, "status": ..., "check_at": iso | None}},  # sun assist
    }

A point is {"time": "HH:MM", "preset": preset_id | "off", "mode": "at"}.
The week starts on Monday (index 0). A room missing from "rooms" has no schedule.
Everything is keyed on the room id (the room's subentry id), never its name.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as dt_time
from collections.abc import Mapping
from typing import Any, Final

SCHEMA_VERSION: Final = 1

# Limits (decided 2026-11-10). Constants, not settings: raising later is easy,
# lowering breaks schedules people already made.
MAX_PRESETS: Final = 10  # Eco and Warm included
MAX_POINTS_PER_DAY: Final = 12
RESOLUTION_MIN: Final = 15
DAYS: Final = 7

PRESET_OFF: Final = "off"  # fixed, uses the system off temperature; never in the preset list
BUILTIN_PRESETS: Final = (("eco", "Eco"), ("warm", "Warm"))

MODE_AT: Final = "at"  # the preset starts at the time
MODE_BY: Final = "by"  # comfort times (v2.1): the room is warm by the time
POINT_MODES: Final = (MODE_AT,)  # v2.0 accepts only "at"; v2.1 adds MODE_BY, no migration

SCHEDULING_ON: Final = "on"
SCHEDULING_OFF: Final = "off"  # the room is the user's: v1 behaviour, no overrides

_PRESET_ID = re.compile(r"^[a-z0-9_]{1,32}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    """Data that breaks a schedule rule. The message is meant for the user."""


# ------------------------------------------------------------------ presets
def builtin_presets() -> list[dict[str, Any]]:
    return [{"id": pid, "name": name, "builtin": True} for pid, name in BUILTIN_PRESETS]


def validate_presets(presets: Any) -> list[dict[str, Any]]:
    """Check the system preset list and return a clean copy."""
    if not isinstance(presets, list):
        raise ScheduleError("Presets must be a list")
    if len(presets) > MAX_PRESETS:
        raise ScheduleError(f"At most {MAX_PRESETS} presets, Eco and Warm included")
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    names: set[str] = set()
    for preset in presets:
        if not isinstance(preset, Mapping):
            raise ScheduleError("A preset must be an object with an id and a name")
        pid = preset.get("id")
        name = str(preset.get("name", "")).strip()
        if not isinstance(pid, str) or not _PRESET_ID.match(pid):
            raise ScheduleError(f"Preset id {pid!r} must be lower case letters, digits or _")
        if pid == PRESET_OFF:
            raise ScheduleError("Off is fixed and can't be a preset of its own")
        if pid in seen:
            raise ScheduleError(f"Preset {pid!r} is listed twice")
        if not name:
            raise ScheduleError(f"Preset {pid!r} needs a name")
        if name.casefold() in names:
            raise ScheduleError(f"Two presets are called {name!r}")
        seen.add(pid)
        names.add(name.casefold())
        clean.append({"id": pid, "name": name, "builtin": pid in dict(BUILTIN_PRESETS)})
    for pid, _ in BUILTIN_PRESETS:
        if pid not in seen:
            raise ScheduleError(f"The built in preset {pid!r} can't be removed")
    return clean


def preset_ids(data: Mapping[str, Any]) -> list[str]:
    return [p["id"] for p in data["presets"]]


# ------------------------------------------------------------- switch points
def parse_time(value: Any) -> int:
    """Minutes after midnight for 'HH:MM' on the 15 minute grid."""
    if not isinstance(value, str) or not (match := _TIME.match(value)):
        raise ScheduleError(f"Time {value!r} must be HH:MM")
    minutes = int(match.group(1)) * 60 + int(match.group(2))
    if minutes % RESOLUTION_MIN:
        raise ScheduleError(f"Time {value} must be on a {RESOLUTION_MIN} minute step")
    return minutes


def validate_point(point: Any, presets: list[str]) -> dict[str, Any]:
    if not isinstance(point, Mapping):
        raise ScheduleError("A switch point must be an object with a time and a preset")
    time = point.get("time")
    parse_time(time)
    preset = point.get("preset")
    if preset != PRESET_OFF and preset not in presets:
        raise ScheduleError(f"Unknown preset {preset!r} at {time}")
    mode = point.get("mode", MODE_AT)
    if mode not in POINT_MODES:
        raise ScheduleError(f"Switch point mode {mode!r} isn't supported yet")
    return {"time": time, "preset": preset, "mode": mode}


def validate_week(week: Any, presets: list[str]) -> list[list[dict[str, Any]]]:
    """Check a week of switch points (Monday first) and return it sorted.

    A day may be empty: the last point before it holds over midnight. The week
    as a whole needs at least one point, or there is nothing to hold.
    """
    if not isinstance(week, list) or len(week) != DAYS:
        raise ScheduleError(f"A week needs {DAYS} days, Monday first")
    clean: list[list[dict[str, Any]]] = []
    for day in week:
        if not isinstance(day, list):
            raise ScheduleError("Each day must be a list of switch points")
        if len(day) > MAX_POINTS_PER_DAY:
            raise ScheduleError(f"At most {MAX_POINTS_PER_DAY} switch points per day")
        points = sorted((validate_point(p, presets) for p in day), key=lambda p: parse_time(p["time"]))
        times = [p["time"] for p in points]
        if len(set(times)) != len(times):
            raise ScheduleError("Two switch points on the same day share a time")
        clean.append(points)
    if not any(clean):
        raise ScheduleError("A schedule needs at least one switch point")
    return clean


def one_block_week(preset: str) -> list[list[dict[str, Any]]]:
    """The easy start: one preset for the whole day, every day."""
    return [[{"time": "00:00", "preset": preset, "mode": MODE_AT}] for _ in range(DAYS)]


def presets_in_week(week: list[list[Mapping[str, Any]]]) -> set[str]:
    return {p["preset"] for day in week for p in day if p["preset"] != PRESET_OFF}


# ------------------------------------------------------- room temperatures
def preset_temperature(data: Mapping[str, Any], room_id: str, preset: str) -> float | None:
    """The room's temperature for a preset; None means Off (Off itself, or not used here)."""
    if preset == PRESET_OFF:
        return None
    value = data["temperatures"].get(room_id, {}).get(preset)
    return None if value is None else float(value)


def unused_presets(data: Mapping[str, Any], room_id: str, week: list[list[Mapping[str, Any]]]) -> set[str]:
    """Presets the week uses that this room marks not used (they mean Off). The card warns on copy."""
    return {p for p in presets_in_week(week) if preset_temperature(data, room_id, p) is None}


# ---------------------------------------------------------------- the data
def empty_data() -> dict[str, Any]:
    return {
        "presets": builtin_presets(),
        "temperatures": {},
        "rooms": {},
        "overrides": {},
        "suspended": False,
        "unsuspended": [],
        "guest": None,
        "sun": {},
    }


def validate_data(data: Any) -> dict[str, Any]:
    """Check stored data as a whole; a ScheduleError means it is left as it is on disk."""
    if not isinstance(data, Mapping):
        raise ScheduleError("Stored schedule data is not an object")
    clean = empty_data()
    clean["presets"] = validate_presets(data.get("presets"))
    ids = preset_ids(clean)
    temps = data.get("temperatures", {})
    if not isinstance(temps, Mapping):
        raise ScheduleError("Preset temperatures must be an object per room")
    for room_id, row in temps.items():
        if not isinstance(row, Mapping):
            raise ScheduleError(f"Preset temperatures of room {room_id} must be an object")
        clean["temperatures"][room_id] = {
            pid: (None if row.get(pid) is None else float(row[pid])) for pid in ids
        }
    rooms = data.get("rooms", {})
    if not isinstance(rooms, Mapping):
        raise ScheduleError("Room schedules must be an object per room")
    for room_id, room in rooms.items():
        scheduling = room.get("scheduling") if isinstance(room, Mapping) else None
        if scheduling not in (SCHEDULING_ON, SCHEDULING_OFF):
            raise ScheduleError(f"Room {room_id}: scheduling must be on or off")
        week = room.get("week")
        if scheduling == SCHEDULING_OFF and week is None:
            clean["rooms"][room_id] = {"scheduling": SCHEDULING_OFF, "week": None}
            continue
        clean["rooms"][room_id] = {"scheduling": scheduling, "week": validate_week(week, ids)}
    overrides = data.get("overrides", {})
    if not isinstance(overrides, Mapping):
        raise ScheduleError("Overrides must be an object per room")
    clean["overrides"] = copy.deepcopy(dict(overrides))  # shape is defined with #116
    clean["suspended"] = bool(data.get("suspended", False))
    unsuspended = data.get("unsuspended", [])
    if not isinstance(unsuspended, list):
        raise ScheduleError("Rooms taken out of the suspend must be a list")
    clean["unsuspended"] = [str(r) for r in unsuspended] if clean["suspended"] else []
    guest = data.get("guest")
    if guest is not None:
        if not isinstance(guest, Mapping) or not (guest.get("until") is None or isinstance(guest["until"], str)):
            raise ScheduleError("Guest mode must be an object with an optional end time")
        clean["guest"] = {"until": guest.get("until")}
    sun = data.get("sun", {})
    if isinstance(sun, Mapping):  # sun assist decisions: dropped rather than refused when odd
        clean["sun"] = {
            str(rid): {"point": rec["point"], "status": rec["status"], "check_at": rec.get("check_at")}
            for rid, rec in sun.items()
            if isinstance(rec, Mapping) and isinstance(rec.get("point"), str)
            and rec.get("status") in ("pending", "holding", "started")
        }
    return clean


def sync_rooms(
    data: dict[str, Any],
    rooms: Mapping[str, tuple[float | None, float | None]],
    defaults: tuple[float, float] = (15.0, 19.0),
) -> bool:
    """Bring the data in line with the rooms that exist. Returns True when it changed.

    `rooms` maps room id to Eco and Warm values handed over by the room form
    (Add room, Edit room, or a v1 room upgraded to v2), None where the form
    handed nothing over. Handed over values replace the stored ones: the file
    is the only place they are kept. A new room gets a column with its Eco and
    Warm (the defaults when none were handed over) and every added preset not
    used. A removed room loses its temperatures, schedule and override (its
    learning records stay elsewhere).
    """
    before = copy.deepcopy(data)
    ids = preset_ids(data)
    temps = data["temperatures"]
    for room_id, handed in rooms.items():
        new = room_id not in temps
        row = temps.setdefault(room_id, {})
        for pid in ids:
            row.setdefault(pid, None)
        for pid, value, default in zip(("eco", "warm"), handed, defaults, strict=True):
            if value is not None:
                row[pid] = float(value)
            elif new or row[pid] is None:
                row[pid] = float(default)
    for key in ("temperatures", "rooms", "overrides", "sun"):
        for room_id in [r for r in data.setdefault(key, {}) if r not in rooms]:
            del data[key][room_id]
    data["unsuspended"] = [r for r in data.get("unsuspended", []) if r in rooms]
    return data != before


# ------------------------------------------------------------ evaluation
# Switch points are local wall time. Instants are aware datetimes. Working with
# instants (never wall times) keeps the daylight saving days right: a point in
# the skipped hour fires at the jump, a point in the repeated hour fires once.
def local_instant(day: date, minutes: int, tz: tzinfo) -> datetime:
    """The first instant the wall clock in `tz` reads day + minutes, or the jump past it."""
    wall = datetime.combine(day, dt_time()) + timedelta(minutes=minutes)
    first = wall.replace(tzinfo=tz, fold=0)
    utc = first.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) == wall:
        return utc  # exists; fold=0 is the first of a repeated time
    # In the skipped hour: fire at the jump, the first instant that reads later
    low = wall.replace(tzinfo=tz, fold=1).astimezone(UTC)
    high = utc
    while high - low > timedelta(minutes=1):
        mid = low + (high - low) / 2
        if mid.astimezone(tz).replace(tzinfo=None) >= wall:
            high = mid
        else:
            low = mid
    for step in range(0, 61):  # land on the whole minute of the jump
        cand = (low + timedelta(minutes=step)).replace(second=0, microsecond=0)
        if cand.astimezone(tz).replace(tzinfo=None) >= wall:
            return cand
    return high


def occurrences(
    week: list[list[Mapping[str, Any]]], now: datetime, tz: tzinfo
) -> list[tuple[datetime, Mapping[str, Any]]]:
    """Every switch point of last week, this week and next week as (instant, point), in order."""
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday())
    out: list[tuple[datetime, Mapping[str, Any]]] = []
    for weeks in (-1, 0, 1):
        for index, day in enumerate(week):
            date_ = monday + timedelta(days=7 * weeks + index)
            out.extend((local_instant(date_, parse_time(p["time"]), tz), p) for p in day)
    out.sort(key=lambda item: item[0])
    return out


def current_occurrence(
    week: list[list[Mapping[str, Any]]], now: datetime, tz: tzinfo
) -> tuple[datetime, Mapping[str, Any]]:
    """The switch point in force now and the instant it started (also over midnight)."""
    past = [item for item in occurrences(week, now, tz) if item[0] <= now]
    return past[-1]  # a week has at least one point, and last week is in the list


def current_point(
    week: list[list[Mapping[str, Any]]], now: datetime, tz: tzinfo
) -> Mapping[str, Any]:
    """The switch point in force now (the last one at or before now, also over midnight)."""
    return current_occurrence(week, now, tz)[1]


def next_change(
    week: list[list[Mapping[str, Any]]], now: datetime, tz: tzinfo
) -> tuple[datetime, Mapping[str, Any]] | None:
    """The next switch point to another preset than the one in force now.

    With a single preset all week (one block) there is no change; the next
    switch point is returned instead, so an override until the next change
    still ends (at the next midnight for one block).
    """
    current = current_point(week, now, tz)["preset"]
    upcoming = [(i, p) for i, p in occurrences(week, now, tz) if i > now]
    for instant, point in upcoming:
        if point["preset"] != current:
            return instant, point
    return upcoming[0] if upcoming else None
