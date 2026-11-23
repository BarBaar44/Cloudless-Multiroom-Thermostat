"""Schedule data model (#112, #113): pure rules, no Home Assistant."""

from __future__ import annotations

import pytest

from custom_components.cloudless_multiroom_thermostat.schedule import (
    MAX_POINTS_PER_DAY,
    MAX_PRESETS,
    PRESET_OFF,
    ScheduleError,
    builtin_presets,
    empty_data,
    one_block_week,
    preset_temperature,
    sync_rooms,
    unused_presets,
    validate_data,
    validate_presets,
    validate_week,
)

IDS = ["eco", "warm", "sleep"]


def _pt(time: str, preset: str = "warm", **extra) -> dict:
    return {"time": time, "preset": preset, **extra}


def _week(*days: list) -> list:
    return [list(d) for d in days] + [[] for _ in range(7 - len(days))]


# ---------------------------------------------------------------- presets
def test_builtin_presets_are_eco_and_warm() -> None:
    assert [p["id"] for p in builtin_presets()] == ["eco", "warm"]
    assert all(p["builtin"] for p in builtin_presets())


def test_added_preset_is_not_builtin() -> None:
    presets = validate_presets([*builtin_presets(), {"id": "sleep", "name": "Sleep", "builtin": True}])
    assert presets[-1] == {"id": "sleep", "name": "Sleep", "builtin": False}


@pytest.mark.parametrize(
    ("presets", "message"),
    [
        ([{"id": "eco", "name": "Eco"}], "can't be removed"),
        ([*builtin_presets(), {"id": "off", "name": "Off"}], "Off is fixed"),
        ([*builtin_presets(), {"id": "eco", "name": "Eco 2"}], "listed twice"),
        ([*builtin_presets(), {"id": "comfy", "name": "eco"}], "Two presets"),
        ([*builtin_presets(), {"id": "Sleep", "name": "Sleep"}], "lower case"),
        ([*builtin_presets(), {"id": "sleep", "name": " "}], "needs a name"),
    ],
)
def test_bad_presets_are_refused(presets, message) -> None:
    with pytest.raises(ScheduleError, match=message):
        validate_presets(presets)


def test_at_most_ten_presets() -> None:
    extra = [{"id": f"p{i}", "name": f"P{i}"} for i in range(MAX_PRESETS - 2)]
    assert len(validate_presets([*builtin_presets(), *extra])) == MAX_PRESETS
    with pytest.raises(ScheduleError, match="At most 10"):
        validate_presets([*builtin_presets(), *extra, {"id": "one_more", "name": "One more"}])


# ------------------------------------------------------------ switch points
def test_week_is_sorted_and_gets_mode_at() -> None:
    week = validate_week(_week([_pt("16:00"), _pt("07:00", "eco")]), IDS)
    assert week[0] == [
        {"time": "07:00", "preset": "eco", "mode": "at"},
        {"time": "16:00", "preset": "warm", "mode": "at"},
    ]


def test_off_and_added_presets_are_allowed() -> None:
    week = validate_week(_week([_pt("22:00", "sleep"), _pt("23:00", PRESET_OFF)]), IDS)
    assert [p["preset"] for p in week[0]] == ["sleep", "off"]


def test_empty_days_are_fine_but_not_an_empty_week() -> None:
    assert validate_week(_week([_pt("00:00")]), IDS)[1] == []
    with pytest.raises(ScheduleError, match="at least one"):
        validate_week(_week(), IDS)


@pytest.mark.parametrize(
    ("day", "message"),
    [
        ([_pt("07:10")], "15 minute"),
        ([_pt("24:00")], "HH:MM"),
        ([_pt("7:00")], "HH:MM"),
        ([_pt("07:00", "party")], "Unknown preset"),
        ([_pt("07:00", mode="by")], "isn't supported yet"),
        ([_pt("07:00"), _pt("07:00", "eco")], "share a time"),
    ],
)
def test_bad_switch_points_are_refused(day, message) -> None:
    with pytest.raises(ScheduleError, match=message):
        validate_week(_week(day), IDS)


def test_at_most_twelve_points_per_day() -> None:
    day = [_pt(f"{h:02d}:00") for h in range(MAX_POINTS_PER_DAY)]
    validate_week(_week(day), IDS)
    with pytest.raises(ScheduleError, match="At most 12"):
        validate_week(_week([*day, _pt("23:00")]), IDS)


def test_week_needs_seven_days() -> None:
    with pytest.raises(ScheduleError, match="7 days"):
        validate_week([[_pt("00:00")]] * 6, IDS)


def test_one_block_week() -> None:
    week = one_block_week("eco")
    assert validate_week(week, IDS) == week
    assert all(day == [{"time": "00:00", "preset": "eco", "mode": "at"}] for day in week)


# ------------------------------------------------------ room temperatures
def _data() -> dict:
    data = empty_data()
    data["presets"] = validate_presets([*builtin_presets(), {"id": "sleep", "name": "Sleep"}])
    sync_rooms(data, {"living": (15.0, 20.5), "office": (15.0, 19.0)})
    data["temperatures"]["living"]["sleep"] = 16.0
    return data


def test_preset_not_used_means_off() -> None:
    data = _data()
    assert preset_temperature(data, "living", "sleep") == 16.0
    assert preset_temperature(data, "office", "sleep") is None
    assert preset_temperature(data, "living", PRESET_OFF) is None


def test_copy_warns_for_presets_the_room_does_not_use() -> None:
    data = _data()
    week = one_block_week("warm")
    week[0].append({"time": "22:00", "preset": "sleep", "mode": "at"})
    assert unused_presets(data, "living", week) == set()
    assert unused_presets(data, "office", week) == {"sleep"}


# ------------------------------------------------------------- sync_rooms
def test_new_rooms_get_eco_and_warm_from_the_room_form() -> None:
    data = empty_data()
    assert sync_rooms(data, {"living": (15.0, 20.5)})
    assert data["temperatures"] == {"living": {"eco": 15.0, "warm": 20.5}}
    assert data["rooms"] == {}  # no schedule yet: #115 decides what that means


def test_room_form_wins_for_eco_and_warm_and_added_presets_stay() -> None:
    data = _data()
    assert sync_rooms(data, {"living": (16.0, 21.0), "office": (15.0, 19.0)})
    assert data["temperatures"]["living"] == {"eco": 16.0, "warm": 21.0, "sleep": 16.0}
    assert not sync_rooms(data, {"living": (16.0, 21.0), "office": (15.0, 19.0)})


def test_removed_room_loses_its_column_schedule_and_override() -> None:
    data = _data()
    data["rooms"]["office"] = {"scheduling": "on", "week": one_block_week("eco")}
    data["overrides"]["office"] = {"target": 21.0}
    assert sync_rooms(data, {"living": (15.0, 20.5)})
    assert "office" not in data["temperatures"]
    assert "office" not in data["rooms"]
    assert "office" not in data["overrides"]


# ---------------------------------------------------------- validate_data
def test_round_trip() -> None:
    data = _data()
    data["rooms"]["living"] = {"scheduling": "on", "week": one_block_week("warm")}
    data["rooms"]["office"] = {"scheduling": "off", "week": None}
    assert validate_data(data) == data


def test_room_column_gets_missing_presets_as_not_used() -> None:
    data = _data()
    del data["temperatures"]["office"]["sleep"]
    assert validate_data(data)["temperatures"]["office"]["sleep"] is None


@pytest.mark.parametrize(
    "breakage",
    [
        lambda d: d.update(presets="eco"),
        lambda d: d["rooms"].update(living={"scheduling": "maybe", "week": None}),
        lambda d: d["rooms"].update(living={"scheduling": "on", "week": None}),
        lambda d: d["rooms"].update(living={"scheduling": "on", "week": _week([_pt("07:00", "party")])}),
    ],
)
def test_broken_data_is_refused(breakage) -> None:
    data = _data()
    breakage(data)
    with pytest.raises(ScheduleError):
        validate_data(data)
