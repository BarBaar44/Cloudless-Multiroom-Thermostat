"""Storage for schedules, presets and overrides (#112).

One HA Store per heating system, not the config entry options: editing a
schedule must never reload the entry. Schema versioned from day one:

- migrations run step by step, and the file is copied to `<file>.v<N>.bak`
  before every migration;
- a file written by a newer version than this code knows is never
  overwritten: scheduling stops with a clear message, and (from #115 on)
  rooms hold the temperature without schedule;
- the same goes for a file that doesn't pass the checks in `schedule.py`.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .schedule import SCHEMA_VERSION, ScheduleError, empty_data, sync_rooms, validate_data

_LOGGER = logging.getLogger(__name__)

# Step N -> N+1, applied in order. Empty until schema 2 exists.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def store_key(entry_id: str) -> str:
    return f"{DOMAIN}.schedule.{entry_id}"


class _ScheduleFile(Store[dict[str, Any]]):
    """HA Store with step by step migrations and a backup before each one."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # HA refuses a newer major version before calling this (UnsupportedStorageVersionError).
        await self.hass.async_add_executor_job(self._backup, old_major_version)
        data = old_data
        for version in range(old_major_version, SCHEMA_VERSION):
            step = MIGRATIONS.get(version)
            if step is None:
                raise ScheduleError(f"No migration from schedule schema {version} to {version + 1}")
            data = step(data)
        return data

    def _backup(self, version: int) -> None:
        if os.path.exists(self.path):
            shutil.copy2(self.path, f"{self.path}.v{version}.bak")


class ScheduleStore:
    """The schedule data of one heating system, loaded once per entry setup."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._file = _ScheduleFile(hass, SCHEMA_VERSION, store_key(entry_id))
        self.data: dict[str, Any] | None = None
        # Why scheduling is stopped, for the log now and the card and Repairs later (#115).
        self.blocked: str | None = None

    @property
    def path(self) -> str:
        return self._file.path

    async def async_load(self, rooms: Mapping[str, tuple[float, float]]) -> None:
        """Load (or create) the data and bring it in line with the rooms that exist.

        Never raises: a problem here stops scheduling, never the heating.
        """
        try:
            stored = await self._file.async_load()
        except HomeAssistantError as err:  # UnsupportedStorageVersionError among them
            self._block(f"Schedules were saved by a newer version of the integration ({err})")
            return
        except ScheduleError as err:
            self._block(f"Schedules couldn't be migrated: {err}")
            return
        if stored is None:
            data = empty_data()
        else:
            try:
                data = validate_data(stored)
            except (ScheduleError, TypeError, ValueError) as err:
                self._block(f"Stored schedules don't pass the checks: {err}")
                return
        changed = sync_rooms(data, rooms) or stored is None
        self.data = data
        if changed:
            await self.async_save()

    async def async_save(self) -> None:
        if self.blocked is not None or self.data is None:
            return  # never overwrite a file this version couldn't read
        await self._file.async_save(self.data)

    async def async_remove(self) -> None:
        """The heating system is deleted: its schedules go with it."""
        await self._file.async_remove()

    def _block(self, reason: str) -> None:
        self.blocked = reason
        self.data = None
        _LOGGER.error(
            "%s. Scheduling is stopped and the file is left as it is: %s", reason, self._file.path
        )
