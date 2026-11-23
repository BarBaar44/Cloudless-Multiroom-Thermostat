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
    }

A point is {"time": "HH:MM", "preset": preset_id | "off", "mode": "at"}.
The week starts on Monday (index 0). A room missing from "rooms" has no schedule.
Everything is keyed on the room id (the room's subentry id), never its name.
"""

from __future__ import annotations

import copy
import re
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
    return clean


def sync_rooms(data: dict[str, Any], rooms: Mapping[str, tuple[float, float]]) -> bool:
    """Bring the data in line with the rooms that exist. Returns True when it changed.

    `rooms` maps room id to its (eco, warm) temperatures from the room form. The
    form is the second place to edit Eco and Warm, so its values win: an edit
    there reloads the entry and lands here. A new room gets a column with its
    Eco and Warm and every added preset not used. A removed room loses its
    temperatures, schedule and override (its learning records stay elsewhere).
    """
    before = copy.deepcopy(data)
    ids = preset_ids(data)
    temps = data["temperatures"]
    for room_id, (eco, warm) in rooms.items():
        row = temps.setdefault(room_id, {})
        for pid in ids:
            row.setdefault(pid, None)
        row["eco"] = float(eco)
        row["warm"] = float(warm)
    for key in ("temperatures", "rooms", "overrides"):
        for room_id in [r for r in data[key] if r not in rooms]:
            del data[key][room_id]
    return data != before
