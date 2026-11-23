"""Cloudless Multiroom Thermostat: multi-room heating from one heat source."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ECO_TEMP,
    CONF_EXPERIMENTAL,
    CONF_WARM_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_WARM_TEMP,
    DOMAIN,
    SERVICE_EXPERIMENTAL_REPORT,
    SERVICE_SET_ALL_OFF,
)
from .controller import HeatingController
from .frontend import async_remove_frontend, async_setup_frontend
from .schedule_store import ScheduleStore

_LOGGER = logging.getLogger(__name__)

# What v2.0.0 changes or removes (#111). Logged once per Home Assistant run.
V2_SCHEDULE_NOTICE = (
    "Cloudless Multiroom Thermostat v2.0.0 will need a schedule for every room: "
    "a room without one holds 15 °C until you make a schedule or turn scheduling off for it. "
    "See Coming: v2.0 in the upgrading docs (docs/upgrading.md)"
)
V2_REPORT_NOTICE = (
    "Cloudless Multiroom Thermostat v2.0.0 removes the 21:00 evening report, the Learning features "
    "report sensor, the Evening notification option and the experimental_report service; "
    "the learning features move to live sensors and a learning view in the card. "
    "See Coming: v2.0 in the upgrading docs (docs/upgrading.md)"
)
_NOTICES_LOGGED: set[str] = set()


def _log_v2_notice(notice: str) -> None:
    if notice not in _NOTICES_LOGGED:
        _NOTICES_LOGGED.add(notice)
        _LOGGER.warning(notice)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR]

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
    _log_v2_notice(V2_SCHEDULE_NOTICE)
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
    v1 move into the schedule file and are then removed from the room. This
    runs before the update listener is added, so removing them doesn't reload.
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
    for room_id, room in controller.rooms.items():
        room.preset_temps = store.temperatures(room_id)
        if CONF_ECO_TEMP in room.config or CONF_WARM_TEMP in room.config:
            room.config = {k: v for k, v in room.config.items() if k not in (CONF_ECO_TEMP, CONF_WARM_TEMP)}
            hass.config_entries.async_update_subentry(entry, entry.subentries[room_id], data=room.config)


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
    if not any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        await async_remove_frontend(hass)
