"""Schedule storage (#112): created, kept in line with the rooms, versioned, never overwritten when newer."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.cloudless_multiroom_thermostat import schedule_store
from custom_components.cloudless_multiroom_thermostat.schedule import SCHEMA_VERSION, one_block_week
from custom_components.cloudless_multiroom_thermostat.schedule_store import ScheduleStore, store_key

from .test_integration import setup  # noqa: F401 - fixture

ROOMS = {"living": (15.0, 20.5), "office": (15.0, 19.0)}
DEFAULTS = (15.0, 19.0)


def _stored(data: dict[str, Any], version: int = SCHEMA_VERSION) -> dict[str, Any]:
    return {"version": version, "minor_version": 1, "key": store_key("e1"), "data": data}


async def test_first_load_creates_eco_and_warm_per_room(hass: HomeAssistant, hass_storage) -> None:
    store = ScheduleStore(hass, "e1")
    await store.async_load(ROOMS, DEFAULTS)
    assert store.blocked is None
    assert store.data["temperatures"] == {
        "living": {"eco": 15.0, "warm": 20.5},
        "office": {"eco": 15.0, "warm": 19.0},
    }
    saved = hass_storage[store_key("e1")]
    assert saved["version"] == SCHEMA_VERSION == 1
    assert saved["data"] == store.data


async def test_load_keeps_schedules_and_drops_removed_rooms(hass: HomeAssistant, hass_storage) -> None:
    first = ScheduleStore(hass, "e1")
    await first.async_load(ROOMS, DEFAULTS)
    first.data["rooms"]["office"] = {"scheduling": "on", "week": one_block_week("eco")}
    first.data["rooms"]["living"] = {"scheduling": "on", "week": one_block_week("warm")}
    await first.async_save()

    again = ScheduleStore(hass, "e1")
    await again.async_load({"living": (None, None)}, DEFAULTS)
    assert list(again.data["rooms"]) == ["living"]
    assert list(again.data["temperatures"]) == ["living"]
    assert list(hass_storage[store_key("e1")]["data"]["rooms"]) == ["living"]


async def test_newer_schema_is_never_overwritten(hass: HomeAssistant, hass_storage, caplog) -> None:
    newer = _stored({"from": "the future"}, version=SCHEMA_VERSION + 1)
    hass_storage[store_key("e1")] = newer
    store = ScheduleStore(hass, "e1")
    with caplog.at_level(logging.ERROR):
        await store.async_load(ROOMS, DEFAULTS)
    assert store.data is None
    assert "newer version" in store.blocked
    assert "Scheduling is stopped" in caplog.text
    await store.async_save()
    assert hass_storage[store_key("e1")] == newer


async def test_broken_file_is_left_alone(hass: HomeAssistant, hass_storage) -> None:
    broken = _stored({"presets": "eco"})
    hass_storage[store_key("e1")] = broken
    store = ScheduleStore(hass, "e1")
    await store.async_load(ROOMS, DEFAULTS)
    assert "don't pass the checks" in store.blocked
    await store.async_save()
    assert hass_storage[store_key("e1")] == broken


async def test_migration_runs_step_by_step_after_a_backup(hass: HomeAssistant, hass_storage) -> None:
    """Pretend the code is at schema 3 and the file at 1."""
    steps: list[int] = []

    def step(version: int):
        def run(data: dict) -> dict:
            steps.append(version)
            return data

        return run

    store = ScheduleStore(hass, "e1")
    store._file.version = 3
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    with open(store.path, "w", encoding="utf-8") as file:
        json.dump(_stored({"presets": []}, version=1), file)
    hass_storage[store_key("e1")] = _stored(
        {"presets": [{"id": "eco", "name": "Eco"}, {"id": "warm", "name": "Warm"}]}, version=1
    )
    try:
        with (
            patch.object(schedule_store, "SCHEMA_VERSION", 3),
            patch.dict(schedule_store.MIGRATIONS, {1: step(1), 2: step(2)}),
        ):
            await store.async_load(ROOMS, DEFAULTS)
        assert steps == [1, 2]
        assert os.path.exists(f"{store.path}.v1.bak")
        assert store.blocked is None
        assert hass_storage[store_key("e1")]["version"] == 3
    finally:
        for path in (store.path, f"{store.path}.v1.bak"):
            if os.path.exists(path):
                os.unlink(path)


async def test_missing_migration_stops_scheduling(hass: HomeAssistant, hass_storage) -> None:
    old = _stored({"presets": []}, version=1)
    hass_storage[store_key("e1")] = old
    store = ScheduleStore(hass, "e1")
    store._file.version = 2
    with patch.object(schedule_store, "SCHEMA_VERSION", 2):
        await store.async_load(ROOMS, DEFAULTS)
    assert "couldn't be migrated" in store.blocked
    assert hass_storage[store_key("e1")] == old


@pytest.mark.usefixtures("hass_storage")
async def test_eco_and_warm_move_from_the_rooms_into_the_file(hass: HomeAssistant, setup) -> None:  # noqa: F811
    """A v1 room keeps Eco and Warm in its settings; setup moves them, so only one copy is left."""
    entry, _ = setup
    store = entry.runtime_data.schedules
    assert store.blocked is None
    by_name = {sub.title: sub.subentry_id for sub in entry.subentries.values()}
    assert store.data["temperatures"][by_name["Living"]] == {"eco": 15.0, "warm": 19.0}
    assert store.data["temperatures"][by_name["Office"]] == {"eco": 15.0, "warm": 18.0}
    assert store.data["rooms"] == {}
    for sub in entry.subentries.values():
        assert "eco_temperature" not in sub.data and "warm_temperature" not in sub.data
        assert "temperature_sensor" in sub.data
    office = entry.runtime_data.rooms[by_name["Office"]]
    assert office.warm_temp == 18.0
    assert office.preset_temps is store.data["temperatures"][by_name["Office"]]


async def test_rooms_keep_eco_and_warm_while_the_file_is_blocked(hass: HomeAssistant, hass_storage) -> None:
    from .test_integration import HALLWAY, LIVING, OFFICE, SYSTEM, _states  # noqa: PLC0415
    from homeassistant.config_entries import ConfigSubentryData  # noqa: PLC0415
    from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: PLC0415

    from custom_components.cloudless_multiroom_thermostat.const import DOMAIN  # noqa: PLC0415

    _states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heating",
        data=SYSTEM,
        subentries_data=[
            ConfigSubentryData(data=data, subentry_type="room", title=data["name"], unique_id=None)
            for data in (LIVING, OFFICE, HALLWAY)
        ],
    )
    entry.add_to_hass(hass)
    newer = _stored({"from": "the future"}, version=SCHEMA_VERSION + 1)
    hass_storage[store_key(entry.entry_id)] = newer
    with patch(
        "custom_components.cloudless_multiroom_thermostat.controller.HeatingController._call",
        lambda *args, **kwargs: _noop(),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    office = next(s for s in entry.subentries.values() if s.title == "Office")
    assert office.data["warm_temperature"] == 18.0
    assert entry.runtime_data.rooms[office.subentry_id].warm_temp == 18.0
    assert hass_storage[store_key(entry.entry_id)] == newer
    assert await hass.config_entries.async_unload(entry.entry_id)


async def _noop() -> None:
    return None


async def test_edit_room_saves_eco_and_warm_in_the_file_only(hass: HomeAssistant, setup) -> None:  # noqa: F811
    from homeassistant.data_entry_flow import FlowResultType  # noqa: PLC0415

    from .test_integration import SENSOR_STEP, _room_step  # noqa: PLC0415

    entry, _ = setup
    office = next(s for s in entry.subentries.values() if s.title == "Office")
    result = await entry.start_subentry_reconfigure_flow(hass, office.subentry_id)
    schema = result["data_schema"].schema
    suggested = {str(k): k.description["suggested_value"] for k in schema if k.description}
    assert suggested["warm_temperature"] == 18.0  # from the file
    flows = hass.config_entries.subentries
    result = await flows.async_configure(result["flow_id"], _room_step("Office", warm_temperature=21.0))
    result = await flows.async_configure(result["flow_id"], SENSOR_STEP)
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert "warm_temperature" not in entry.subentries[office.subentry_id].data
    store = entry.runtime_data.schedules
    assert store.data["temperatures"][office.subentry_id]["warm"] == 21.0
    assert entry.runtime_data.rooms[office.subentry_id].warm_temp == 21.0


async def test_removing_the_system_removes_its_schedules(hass: HomeAssistant, setup, hass_storage) -> None:  # noqa: F811
    entry, _ = setup
    assert store_key(entry.entry_id) in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert store_key(entry.entry_id) not in hass_storage
