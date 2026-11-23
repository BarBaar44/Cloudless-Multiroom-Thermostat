"""Cloudless Multiroom Thermostat: multi-room heating from one heat source."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ECO_TEMP,
    CONF_EXPERIMENTAL,
    CONF_INITIAL_SCHEDULE,
    CONF_WARM_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_WARM_TEMP,
    DOMAIN,
    SCHEDULING_OFF_CHOICE,
    SERVICE_EXPERIMENTAL_REPORT,
    SERVICE_RESUME_SCHEDULES,
    SERVICE_SET_ALL_OFF,
    SERVICE_SET_GUEST_MODE,
    SERVICE_SET_PRESETS,
    SERVICE_SUSPEND_SCHEDULES,
)
from .controller import HeatingController
from .frontend import async_remove_frontend, async_setup_frontend
from .schedule import SCHEDULING_OFF, SCHEDULING_ON, one_block_week
from .schedule_store import ScheduleStore
from .scheduler import issue_ids

_LOGGER = logging.getLogger(__name__)

# What a coming version changes or removes (#111). Logged once per Home Assistant run.
# The schedule notice went with v2.0.0 itself; the report moves to v2.1 (2026-11-23).
V2_REPORT_NOTICE = (
    "Cloudless Multiroom Thermostat v2.1.0 removes the 21:00 evening report, the Learning features "
    "report sensor, the Evening notification option and the experimental_report service; "
    "the learning features move to live sensors and a learning view in the card. "
    "See the upgrading docs (docs/upgrading.md)"
)
_NOTICES_LOGGED: set[str] = set()


def _log_v2_notice(notice: str) -> None:
    if notice not in _NOTICES_LOGGED:
        _NOTICES_LOGGED.add(notice)
        _LOGGER.warning(notice)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type CMTConfigEntry = ConfigEntry[HeatingController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register domain services and the bundled dashboard card."""
    await async_setup_frontend(hass)

    async def _set_all_off(call: ServiceCall) -> None:
        entry_ids = call.data.get("config_entry_id")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if entry_ids and entry.entry_id not in entry_ids:
                continue
            controller: HeatingController = entry.runtime_data
            for room_id in controller.rooms:
                controller.set_room_state(room_id, hvac_on=False)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ALL_OFF,
        _set_all_off,
        schema=vol.Schema({vol.Optional("config_entry_id"): vol.All(cv.ensure_list, [cv.string])}),
    )

    def _suspend(suspended: bool):
        async def _handler(call: ServiceCall) -> None:
            entry_ids = call.data.get("config_entry_id")
            for entry in hass.config_entries.async_loaded_entries(DOMAIN):
                if entry_ids and entry.entry_id not in entry_ids:
                    continue
                await entry.runtime_data.scheduler.async_suspend(suspended)

        return _handler

    for service, suspended in ((SERVICE_SUSPEND_SCHEDULES, True), (SERVICE_RESUME_SCHEDULES, False)):
        hass.services.async_register(
            DOMAIN,
            service,
            _suspend(suspended),
            schema=vol.Schema({vol.Optional("config_entry_id"): vol.All(cv.ensure_list, [cv.string])}),
        )

    def _system(call: ServiceCall) -> CMTConfigEntry:
        """The heating system a call is for: config_entry_id, or the only one there is."""
        loaded = hass.config_entries.async_loaded_entries(DOMAIN)
        wanted = call.data.get("config_entry_id")
        if wanted:
            loaded = [e for e in loaded if e.entry_id in wanted]
        if len(loaded) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="which_system")
        return loaded[0]

    async def _set_presets(call: ServiceCall) -> None:
        entry = _system(call)
        registry = er.async_get(hass)
        temperatures: dict[str, Any] = {}
        for entity_id, values in (call.data.get("temperatures") or {}).items():
            reg = registry.async_get(entity_id)
            room_id = reg.unique_id.removesuffix("_climate") if reg and reg.config_entry_id == entry.entry_id else None
            if room_id is None or room_id not in entry.runtime_data.rooms:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="not_a_room", translation_placeholders={"entity": entity_id}
                )
            temperatures[room_id] = values
        await entry.runtime_data.scheduler.async_set_presets(call.data.get("presets"), temperatures)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PRESETS,
        _set_presets,
        schema=vol.Schema(
            {
                vol.Optional("config_entry_id"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("presets"): [
                    vol.Schema(
                        {
                            vol.Optional("id"): cv.string,
                            vol.Required("name"): cv.string,
                            vol.Optional("color"): vol.Any(None, cv.string),
                        },
                        extra=vol.REMOVE_EXTRA,
                    )
                ],
                vol.Optional("temperatures"): {cv.entity_id: {cv.string: vol.Any(None, vol.Coerce(float))}},
            }
        ),
    )

    async def _set_guest_mode(call: ServiceCall) -> None:
        entry_ids = call.data.get("config_entry_id")
        until = call.data.get("until")
        if (duration := call.data.get("duration")) is not None:
            until = dt_util.utcnow() + duration
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if entry_ids and entry.entry_id not in entry_ids:
                continue
            await entry.runtime_data.scheduler.async_set_guest(call.data["on"], until)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_GUEST_MODE,
        _set_guest_mode,
        schema=vol.Schema(
            {
                vol.Optional("config_entry_id"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("on", default=True): cv.boolean,
                vol.Exclusive("until", "end"): cv.datetime,
                vol.Exclusive("duration", "end"): vol.All(cv.time_period, cv.positive_timedelta),
            }
        ),
    )

    async def _experimental_report(call: ServiceCall) -> None:
        _LOGGER.warning("The experimental_report service is removed in v2.0.0 (deprecated)")
        entry_ids = call.data.get("config_entry_id")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if entry_ids and entry.entry_id not in entry_ids:
                continue
            runner = entry.runtime_data.experimental
            if runner is not None:
                await runner.async_report()

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPERIMENTAL_REPORT,
        _experimental_report,
        schema=vol.Schema({vol.Optional("config_entry_id"): vol.All(cv.ensure_list, [cv.string])}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CMTConfigEntry) -> bool:
    controller = HeatingController(hass, entry)
    entry.runtime_data = controller
    if controller.settings.get(CONF_EXPERIMENTAL):
        _log_v2_notice(V2_REPORT_NOTICE)
        from .experimental.runner import ExperimentalRunner  # noqa: PLC0415

        controller.experimental = ExperimentalRunner(hass, controller)

    system_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Cloudless Multiroom Thermostat",
        model="Heating system",
    )
    controller.system_device_id = system_device.id

    await _async_load_schedules(hass, entry, controller)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    if controller.experimental is not None:
        await _async_start_learning(controller)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_load_schedules(hass: HomeAssistant, entry: CMTConfigEntry, controller: HeatingController) -> None:
    """Load the v2 schedule data (#112) and make it the only home of the preset temperatures.

    Eco and Warm handed over by the room form (Add room, Edit room) or left by
    v1, and the schedule chosen in Add room, move into the schedule file and are
    then removed from the room. This runs before the update listener is added,
    so removing them doesn't reload.
    Nothing acts on schedules yet. A problem here stops scheduling, never the
    heating: the values then stay with the room until the file can be used.
    """
    store = ScheduleStore(hass, entry.entry_id)
    controller.schedules = store
    await store.async_load(
        {
            room_id: (room.config.get(CONF_ECO_TEMP), room.config.get(CONF_WARM_TEMP))
            for room_id, room in controller.rooms.items()
        },
        (DEFAULT_ECO_TEMP, DEFAULT_WARM_TEMP),
    )
    if store.blocked is not None:
        return
    handed_over = (CONF_ECO_TEMP, CONF_WARM_TEMP, CONF_INITIAL_SCHEDULE)
    schedules_added = False
    for room_id, room in controller.rooms.items():
        room.preset_temps = store.temperatures(room_id)
        choice = room.config.get(CONF_INITIAL_SCHEDULE)
        if choice and room_id not in store.data["rooms"]:
            if choice == SCHEDULING_OFF_CHOICE:
                store.data["rooms"][room_id] = {"scheduling": SCHEDULING_OFF, "week": None}
            elif choice in store.data["temperatures"].get(room_id, {}):
                store.data["rooms"][room_id] = {"scheduling": SCHEDULING_ON, "week": one_block_week(choice)}
            schedules_added = True
        if any(key in room.config for key in handed_over):
            room.config = {k: v for k, v in room.config.items() if k not in handed_over}
            hass.config_entries.async_update_subentry(entry, entry.subentries[room_id], data=room.config)
    if schedules_added:
        await store.async_save()


async def _async_start_learning(controller: HeatingController) -> None:
    """Start the learning features; a failure there must never stop the heating."""
    runner = controller.experimental
    try:
        await runner.async_start()
    except Exception:  # noqa: BLE001 - observe only: log it and heat on without them
        _LOGGER.exception("Learning features failed to start; the heating runs without them")
        try:
            await runner.async_stop()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Stopping the learning features after a failed start failed too", exc_info=True)


async def async_unload_entry(hass: HomeAssistant, entry: CMTConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        if entry.runtime_data.experimental is not None:
            await entry.runtime_data.experimental.async_stop()
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: CMTConfigEntry) -> None:
    """Options changed or a room was added, edited or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: CMTConfigEntry) -> None:
    """Remove the system's schedules, and the card's dashboard resource with the last system."""
    await ScheduleStore(hass, entry.entry_id).async_remove()
    for issue_id in issue_ids(entry.entry_id):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    if not any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        await async_remove_frontend(hass)
