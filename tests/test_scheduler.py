"""The scheduler (#114, #115): rooms follow their schedule, rooms without one hold 15 °C."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cloudless_multiroom_thermostat.const import DOMAIN
from custom_components.cloudless_multiroom_thermostat.schedule import (
    current_point,
    local_instant,
    next_change,
    one_block_week,
)
from custom_components.cloudless_multiroom_thermostat.schedule_store import store_key

from .test_integration import HALLWAY, LIVING, OFFICE, SYSTEM, _states

pytestmark = pytest.mark.v2_schedules

AMS = ZoneInfo("Europe/Amsterdam")
# Monday 23 November 2026, 12:00 in Amsterdam (CET, UTC+1)
MONDAY_NOON = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)


def _pt(time: str, preset: str) -> dict:
    return {"time": time, "preset": preset, "mode": "at"}


def _every_day(*points: dict) -> list:
    return [list(points) for _ in range(7)]


# ------------------------------------------------------------- pure rules
def test_point_holds_over_midnight_and_over_empty_days() -> None:
    week = [[] for _ in range(7)]
    week[6] = [_pt("22:00", "eco")]  # only Sunday evening
    tuesday = datetime(2026, 11, 24, 12, 0, tzinfo=AMS)
    assert current_point(week, tuesday, AMS)["preset"] == "eco"


def test_next_change_skips_points_to_the_same_preset() -> None:
    week = _every_day(_pt("07:00", "warm"), _pt("12:00", "warm"), _pt("22:00", "eco"))
    at, point = next_change(week, datetime(2026, 11, 23, 8, 0, tzinfo=AMS), AMS)
    assert at.astimezone(AMS) == datetime(2026, 11, 23, 22, 0, tzinfo=AMS)
    assert point["preset"] == "eco"


def test_one_block_changes_at_midnight() -> None:
    at, point = next_change(one_block_week("warm"), datetime(2026, 11, 23, 8, 0, tzinfo=AMS), AMS)
    assert at.astimezone(AMS) == datetime(2026, 11, 24, 0, 0, tzinfo=AMS)


def test_point_in_the_skipped_hour_fires_at_the_jump() -> None:
    at = local_instant(date(2026, 3, 29), 2 * 60 + 30, AMS)
    assert at.astimezone(AMS).hour == 3 and at.astimezone(AMS).minute == 0


def test_point_in_the_repeated_hour_fires_once() -> None:
    week = [[] for _ in range(7)]
    week[6] = [_pt("02:30", "warm"), _pt("05:00", "eco")]  # Sunday 25 October 2026
    first = local_instant(date(2026, 10, 25), 150, AMS)
    assert first == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 02:30 summer time
    # At the second 02:30 (winter time) the next change is 05:00, not 02:30 again
    second = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    at, point = next_change(week, second, AMS)
    assert point["preset"] == "eco"


# ------------------------------------------------------- in Home Assistant
@pytest.fixture
async def house(hass: HomeAssistant, hass_storage, freezer):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to(MONDAY_NOON)
    _states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heating",
        data=SYSTEM,
        options={"feature_guest_mode": True},
        subentries_data=[
            ConfigSubentryData(data=data, subentry_type="room", title=data["name"], unique_id=None)
            for data in (LIVING, OFFICE, HALLWAY)
        ],
    )
    entry.add_to_hass(hass)

    async def _fake_call(self, domain, service, data, key=None):
        return None

    with patch(
        "custom_components.cloudless_multiroom_thermostat.controller.HeatingController._call", _fake_call
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


def _room(hass: HomeAssistant, name: str) -> dict[str, Any]:
    state = hass.states.get(f"climate.{name}")
    return {"state": state.state, **state.attributes}


async def _call(hass: HomeAssistant, service: str, entity: str, domain: str = "climate", **data) -> None:
    await hass.services.async_call(domain, service, {"entity_id": entity, **data}, blocking=True)
    await hass.async_block_till_done()


async def _schedule(hass: HomeAssistant, entity: str, week: list | None = None, scheduling: str = "on") -> None:
    data: dict[str, Any] = {"scheduling": scheduling}
    if week is not None:
        data["week"] = week
    await _call(hass, "set_schedule", entity, domain=DOMAIN, **data)


async def _at(hass: HomeAssistant, freezer, when: datetime) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_rooms_without_schedule_hold_15(hass: HomeAssistant, house) -> None:
    living = _room(hass, "living")
    assert living["schedule_state"] == "none"
    assert living["temperature"] == 15.0
    assert living["preset_mode"] == "none"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"no_schedule_{house.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders["rooms"] == "Hallway, Living, Office"


async def test_target_and_preset_are_refused_without_schedule(hass: HomeAssistant, house) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "set_temperature", "climate.living", temperature=21)
    assert err.value.translation_key == "no_schedule"
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_preset_mode", "climate.living", preset_mode="warm")
    assert _room(hass, "living")["temperature"] == 15.0
    # Off is always allowed, and heat again
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="off")
    assert _room(hass, "living")["state"] == "off"
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="heat")
    assert _room(hass, "living")["temperature"] == 15.0


async def test_room_follows_its_schedule(hass: HomeAssistant, house, freezer) -> None:
    week = _every_day(_pt("07:00", "warm"), _pt("22:00", "eco"))
    await _schedule(hass, "climate.living", week)
    living = _room(hass, "living")
    assert living["schedule_state"] == "active"
    assert living["preset_mode"] == "warm" and living["temperature"] == 19.0
    assert living["next_change"] == {"at": "2026-11-23T22:00:00+01:00", "preset": "eco"}
    await _at(hass, freezer, datetime(2026, 11, 23, 21, 0, tzinfo=UTC))  # 22:00 local
    living = _room(hass, "living")
    assert living["preset_mode"] == "eco" and living["temperature"] == 15.0


async def test_switch_point_to_off(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.office", one_block_week("off"))
    office = _room(hass, "office")
    assert office["preset_mode"] == "off" and office["temperature"] == 10.0
    assert "off" in office["preset_modes"]


async def test_manual_change_lasts_until_the_next_change(hass: HomeAssistant, house, freezer) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _call(hass, "set_temperature", "climate.living", temperature=21)
    living = _room(hass, "living")
    assert living["temperature"] == 21.0 and living["preset_mode"] == "none"
    assert living["override_until"] == "2026-11-23T22:00:00+01:00"
    await _at(hass, freezer, datetime(2026, 11, 23, 21, 0, tzinfo=UTC))
    living = _room(hass, "living")
    assert living["temperature"] == 15.0 and living["override_until"] is None


async def test_preset_by_hand_and_back_to_schedule(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _call(hass, "set_preset_mode", "climate.living", preset_mode="eco")
    assert _room(hass, "living")["preset_mode"] == "eco"
    assert _room(hass, "living")["override_until"] is not None
    await _call(hass, "set_preset_mode", "climate.living", preset_mode="none")
    assert _room(hass, "living")["preset_mode"] == "warm"
    await _call(hass, "set_temperature", "climate.living", temperature=21)
    await _call(hass, "resume_schedule", "climate.living", domain=DOMAIN)
    assert _room(hass, "living")["temperature"] == 19.0


async def test_off_is_off(hass: HomeAssistant, house, freezer) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="off")
    await _at(hass, freezer, datetime(2026, 11, 23, 21, 0, tzinfo=UTC))
    living = _room(hass, "living")
    assert living["state"] == "off"
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="heat")
    assert _room(hass, "living")["preset_mode"] == "eco"  # what the schedule says now


async def test_suspend_holds_15_for_scheduled_rooms_only(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _schedule(hass, "climate.office", scheduling="off")
    await _call(hass, "set_temperature", "climate.office", temperature=20)
    await hass.services.async_call(DOMAIN, "suspend_schedules", {}, blocking=True)
    await hass.async_block_till_done()
    assert _room(hass, "living")["schedule_state"] == "suspended"
    assert _room(hass, "living")["temperature"] == 15.0
    assert _room(hass, "office")["temperature"] == 20.0
    await hass.services.async_call(DOMAIN, "resume_schedules", {}, blocking=True)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 19.0


async def test_change_by_hand_starts_that_rooms_schedule_while_suspended(hass: HomeAssistant, house, freezer) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _schedule(hass, "climate.office", one_block_week("warm"))
    await hass.services.async_call(DOMAIN, "suspend_schedules", {}, blocking=True)
    await hass.async_block_till_done()
    await _call(hass, "set_temperature", "climate.living", temperature=21)
    living = _room(hass, "living")
    assert living["schedule_state"] == "active" and living["temperature"] == 21.0
    assert living["override_until"] == "2026-11-23T22:00:00+01:00"
    assert _room(hass, "office")["schedule_state"] == "suspended"  # only that room
    await _at(hass, freezer, datetime(2026, 11, 23, 21, 0, tzinfo=UTC))
    assert _room(hass, "living")["temperature"] == 15.0  # its schedule: eco
    # Suspending again takes every room back in
    await hass.services.async_call(DOMAIN, "resume_schedules", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "suspend_schedules", {}, blocking=True)
    await hass.async_block_till_done()
    assert _room(hass, "living")["schedule_state"] == "suspended"


async def test_scheduling_off_is_v1(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.office", scheduling="off")
    await _call(hass, "set_preset_mode", "climate.office", preset_mode="warm")
    assert _room(hass, "office")["temperature"] == 18.0
    await _call(hass, "set_temperature", "climate.office", temperature=20)
    office = _room(hass, "office")
    assert office["temperature"] == 20.0 and office["schedule_state"] == "off"
    assert office["override_until"] is None


async def test_scheduling_back_on_returns_to_the_week(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("eco"))
    await _schedule(hass, "climate.living", scheduling="off")
    await _schedule(hass, "climate.living")
    assert _room(hass, "living")["preset_mode"] == "eco"
    with pytest.raises(ServiceValidationError) as err:
        await _schedule(hass, "climate.office")  # never had one
    assert err.value.translation_key == "no_week"


async def test_bad_week_is_refused(hass: HomeAssistant, house) -> None:
    with pytest.raises(ServiceValidationError, match="15 minute"):
        await _schedule(hass, "climate.living", _every_day(_pt("07:10", "warm")))


async def test_repairs_issue_goes_when_every_room_is_settled(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _schedule(hass, "climate.office", one_block_week("eco"))
    issue_id = f"no_schedule_{house.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id).translation_placeholders["rooms"] == "Hallway"
    await _schedule(hass, "climate.hallway", scheduling="off")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_override_survives_a_restart_until_it_ends(hass: HomeAssistant, house, freezer, hass_storage) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _call(hass, "set_temperature", "climate.living", temperature=21)
    assert await hass.config_entries.async_reload(house.entry_id)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 21.0
    # Down over the end of the override: it is dropped on the way back up
    assert await hass.config_entries.async_unload(house.entry_id)
    freezer.move_to(datetime(2026, 11, 23, 22, 0, tzinfo=UTC))
    assert await hass.config_entries.async_setup(house.entry_id)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 15.0
    await _at(hass, freezer, datetime(2026, 11, 23, 22, 0, 5, tzinfo=UTC))  # the delayed save
    assert hass_storage[store_key(house.entry_id)]["data"]["overrides"] == {}


async def test_blocked_file_holds_every_room_at_15(hass: HomeAssistant, hass_storage) -> None:
    _states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Heating", data=SYSTEM,
        subentries_data=[ConfigSubentryData(data=LIVING, subentry_type="room", title="Living", unique_id=None)],
    )
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = {"version": 99, "minor_version": 1, "key": "x", "data": {}}

    async def _fake_call(self, domain, service, data, key=None):
        return None

    with patch(
        "custom_components.cloudless_multiroom_thermostat.controller.HeatingController._call", _fake_call
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert _room(hass, "living")["schedule_state"] == "blocked"
    assert _room(hass, "living")["temperature"] == 15.0
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"schedules_blocked_{entry.entry_id}") is not None
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_temperature", "climate.living", temperature=21)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_temperature_without_schedule_is_a_setting(hass: HomeAssistant, house) -> None:
    hass.config_entries.async_update_entry(house, options={**house.options, "temperature_without_schedule": 12.0})
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 12.0


def test_dst_helpers_cover_the_week_around_now() -> None:
    # Sanity: every point of a week appears three times (last, this and next week)
    from custom_components.cloudless_multiroom_thermostat.schedule import occurrences  # noqa: PLC0415

    week = _every_day(_pt("07:00", "warm"))
    assert len(occurrences(week, MONDAY_NOON, AMS)) == 21
    assert occurrences(week, MONDAY_NOON, AMS)[0][0] < MONDAY_NOON - timedelta(days=6)


# ---------------------------------------------------------------- #116
async def _override(hass: HomeAssistant, entity: str, **data) -> None:
    await _call(hass, "set_override", entity, domain=DOMAIN, **data)


async def _presence(hass: HomeAssistant, home: bool) -> None:
    hass.states.async_set("input_boolean.somebody_home", "on" if home else "off")
    await hass.async_block_till_done()


async def test_override_for_a_duration(hass: HomeAssistant, house, freezer) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _override(hass, "climate.living", temperature=21, duration={"hours": 1})
    living = _room(hass, "living")
    assert living["temperature"] == 21.0
    assert living["override"]["until"] == "2026-11-23T13:00:00+01:00"
    await _at(hass, freezer, MONDAY_NOON + timedelta(hours=1))
    assert _room(hass, "living")["temperature"] == 19.0


async def test_override_until_back_to_schedule(hass: HomeAssistant, house, freezer) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _override(hass, "climate.living", preset="eco", until="permanent")
    await _at(hass, freezer, datetime(2026, 11, 24, 7, 0, tzinfo=UTC))  # past several changes
    living = _room(hass, "living")
    assert living["preset_mode"] == "eco" and living["override"]["until"] is None
    await _call(hass, "resume_schedule", "climate.living", domain=DOMAIN)
    assert _room(hass, "living")["preset_mode"] == "warm"


async def test_override_without_until_uses_next_change(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "eco")))
    await _override(hass, "climate.living", temperature=20.5)
    assert _room(hass, "living")["override_until"] == "2026-11-23T22:00:00+01:00"


async def test_override_needs_a_temperature_or_a_preset(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    with pytest.raises(ServiceValidationError) as err:
        await _override(hass, "climate.living", until="permanent")
    assert err.value.translation_key == "override_target_or_preset"


async def test_override_on_scheduling_off_is_refused(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.office", scheduling="off")
    with pytest.raises(ServiceValidationError) as err:
        await _override(hass, "climate.office", temperature=21)
    assert err.value.translation_key == "scheduling_off"


async def test_overrides_go_when_everyone_leaves(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="heat")
    await _override(hass, "climate.living", temperature=21, until="permanent")
    await _presence(hass, False)
    living = _room(hass, "living")
    assert living["override"] is None and living["temperature"] == 19.0
    assert living["paused_reason"] == "away"
    await _presence(hass, True)
    assert _room(hass, "living")["temperature"] == 19.0  # what the schedule says now


async def test_override_kept_when_away_ranks_above_away(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.office", one_block_week("eco"))
    await _call(hass, "set_hvac_mode", "climate.office", hvac_mode="heat")
    await _override(hass, "climate.office", temperature=20, duration={"hours": 3}, keep_when_away=True)
    await _presence(hass, False)
    office = _room(hass, "office")
    assert office["override"]["keep_when_away"] is True
    assert office["paused_reason"] is None
    assert office["effective_target"] == 20.0


# ---------------------------------------------------------------- #117
async def test_guest_mode_ignores_presence(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="heat")
    await _call(hass, "turn_on", "switch.heating_someone_is_home_guest_mode", domain="switch")
    await _presence(hass, False)
    living = _room(hass, "living")
    assert living["paused_reason"] is None and living["effective_target"] == 19.0
    await _call(hass, "turn_off", "switch.heating_someone_is_home_guest_mode", domain="switch")
    assert _room(hass, "living")["paused_reason"] == "away"


async def test_overrides_stay_while_guest_mode_is_on_and_go_when_it_ends(
    hass: HomeAssistant, house, freezer
) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _call(hass, "set_hvac_mode", "climate.living", hvac_mode="heat")
    await _override(hass, "climate.living", temperature=21, until="permanent")
    await hass.services.async_call(DOMAIN, "set_guest_mode", {"duration": {"hours": 2}}, blocking=True)
    await hass.async_block_till_done()
    guest = hass.states.get("switch.heating_someone_is_home_guest_mode")
    assert guest.state == "on" and guest.attributes["until"] == "2026-11-23T14:00:00+01:00"
    await _presence(hass, False)
    assert _room(hass, "living")["temperature"] == 21.0  # someone is home: away hasn't started
    await _at(hass, freezer, MONDAY_NOON + timedelta(hours=2))
    assert hass.states.get("switch.heating_someone_is_home_guest_mode").state == "off"
    living = _room(hass, "living")
    assert living["override"] is None and living["paused_reason"] == "away"


async def test_guest_mode_survives_a_restart(hass: HomeAssistant, house) -> None:
    await hass.services.async_call(DOMAIN, "set_guest_mode", {}, blocking=True)
    assert await hass.config_entries.async_reload(house.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.heating_someone_is_home_guest_mode").state == "on"


async def test_guest_mode_end_in_the_past_is_refused(hass: HomeAssistant, house) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_guest_mode", {"until": "2026-11-23T10:00:00+01:00"}, blocking=True
        )
    assert err.value.translation_key == "guest_end_in_past"


# ---------------------------------------------------------------- #113
async def _presets(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(DOMAIN, "set_presets", data, blocking=True)
    await hass.async_block_till_done()


async def test_add_a_preset_with_temperatures_and_colour(hass: HomeAssistant, house) -> None:
    await _presets(
        hass,
        presets=[{"id": "eco", "name": "Eco"}, {"id": "warm", "name": "Warm", "color": "#ff5722"}, {"name": "Sleep"}],
        temperatures={"climate.living": {"sleep": 16.5}},
    )
    living = _room(hass, "living")
    assert living["presets"] == [
        {"id": "eco", "name": "Eco", "color": None, "temperature": 15.0},
        {"id": "warm", "name": "Warm", "color": "#ff5722", "temperature": 19.0},
        {"id": "sleep", "name": "Sleep", "color": None, "temperature": 16.5},
    ]
    assert _room(hass, "office")["presets"][2]["temperature"] is None  # not used there
    await _schedule(hass, "climate.office", one_block_week("sleep"))
    office = _room(hass, "office")
    assert office["preset_mode"] == "sleep" and office["temperature"] == 10.0  # not used means Off
    assert "sleep" in office["preset_modes"]


async def test_changing_a_preset_temperature_applies_now(hass: HomeAssistant, house) -> None:
    await _schedule(hass, "climate.living", one_block_week("warm"))
    await _presets(hass, temperatures={"climate.living": {"warm": 20.5}})
    assert _room(hass, "living")["temperature"] == 20.5
    # The room form shows the same value: one copy, in the schedule file
    assert house.runtime_data.rooms[next(
        r for r, room in house.runtime_data.rooms.items() if room.name == "Living"
    )].warm_temp == 20.5


async def test_a_preset_in_use_can_not_be_removed(hass: HomeAssistant, house) -> None:
    await _presets(hass, presets=[{"id": "eco", "name": "Eco"}, {"id": "warm", "name": "Warm"}, {"name": "Sleep"}])
    await _schedule(hass, "climate.living", _every_day(_pt("07:00", "warm"), _pt("22:00", "sleep")))
    with pytest.raises(ServiceValidationError) as err:
        await _presets(hass, presets=[{"id": "eco", "name": "Eco"}, {"id": "warm", "name": "Warm"}])
    assert err.value.translation_key == "preset_in_use"
    assert err.value.translation_placeholders["rooms"] == "Living"


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"temperatures": {"climate.living": {"warm": None}}}, "builtin_needs_temperature"),
        ({"temperatures": {"climate.living": {"warm": 40}}}, "temperature_out_of_range"),
        ({"temperatures": {"climate.living": {"party": 20}}}, "unknown_preset"),
        ({"temperatures": {"switch.ch_enabled": {"warm": 20}}}, "not_a_room"),
    ],
)
async def test_bad_preset_changes_are_refused(hass: HomeAssistant, house, data, key) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _presets(hass, **data)
    assert err.value.translation_key == key


async def test_bad_preset_list_is_refused(hass: HomeAssistant, house) -> None:
    with pytest.raises(ServiceValidationError, match="can't be removed"):
        await _presets(hass, presets=[{"id": "eco", "name": "Eco"}])
    with pytest.raises(ServiceValidationError, match="#ff5722"):
        await _presets(hass, presets=[{"id": "eco", "name": "Eco", "color": "orange"}, {"id": "warm", "name": "Warm"}])
