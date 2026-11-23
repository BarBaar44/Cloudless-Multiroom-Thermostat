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


def _stored(data: dict[str, Any], version: int = SCHEMA_VERSION) -> dict[str, Any]:
    return {"version": version, "minor_version": 1, "key": store_key("e1"), "data": data}


async def test_first_load_creates_eco_and_warm_per_room(hass: HomeAssistant, hass_storage) -> None:
    store = ScheduleStore(hass, "e1")
    await store.async_load(ROOMS)
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
    await first.async_load(ROOMS)
    first.data["rooms"]["office"] = {"scheduling": "on", "week": one_block_week("eco")}
    first.data["rooms"]["living"] = {"scheduling": "on", "week": one_block_week("warm")}
    await first.async_save()

    again = ScheduleStore(hass, "e1")
    await again.async_load({"living": (15.0, 20.5)})
    assert list(again.data["rooms"]) == ["living"]
    assert list(again.data["temperatures"]) == ["living"]
    assert list(hass_storage[store_key("e1")]["data"]["rooms"]) == ["living"]


async def test_newer_schema_is_never_overwritten(hass: HomeAssistant, hass_storage, caplog) -> None:
    newer = _stored({"from": "the future"}, version=SCHEMA_VERSION + 1)
    hass_storage[store_key("e1")] = newer
    store = ScheduleStore(hass, "e1")
    with caplog.at_level(logging.ERROR):
        await store.async_load(ROOMS)
    assert store.data is None
    assert "newer version" in store.blocked
    assert "Scheduling is stopped" in caplog.text
    await store.async_save()
    assert hass_storage[store_key("e1")] == newer


async def test_broken_file_is_left_alone(hass: HomeAssistant, hass_storage) -> None:
    broken = _stored({"presets": "eco"})
    hass_storage[store_key("e1")] = broken
    store = ScheduleStore(hass, "e1")
    await store.async_load(ROOMS)
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
            await store.async_load(ROOMS)
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
        await store.async_load(ROOMS)
    assert "couldn't be migrated" in store.blocked
    assert hass_storage[store_key("e1")] == old


@pytest.mark.usefixtures("hass_storage")
async def test_setup_loads_the_store_from_the_room_forms(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    store = entry.runtime_data.schedules
    assert store.blocked is None
    by_name = {sub.title: sub.subentry_id for sub in entry.subentries.values()}
    assert store.data["temperatures"][by_name["Living"]] == {"eco": 15.0, "warm": 19.0}
    assert store.data["temperatures"][by_name["Office"]] == {"eco": 15.0, "warm": 18.0}
    assert store.data["rooms"] == {}


async def test_removing_the_system_removes_its_schedules(hass: HomeAssistant, setup, hass_storage) -> None:  # noqa: F811
    entry, _ = setup
    assert store_key(entry.entry_id) in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert store_key(entry.entry_id) not in hass_storage
