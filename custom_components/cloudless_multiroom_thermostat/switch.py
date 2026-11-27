"""Guest mode (#117): a system wide "someone is home" switch that ignores presence."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CMTConfigEntry
from .const import signal_update
from .controller import HeatingController
from .entity import remove_entity, system_device_info
from .features import FEATURE_GUEST


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CMTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.feature(FEATURE_GUEST):
        async_add_entities([GuestModeSwitch(entry.runtime_data)])
    else:
        remove_entity(hass, "switch", f"{entry.entry_id}_guest_mode")


class GuestModeSwitch(SwitchEntity):
    """On: the whole house runs its schedules as if someone is home, until switched off or the end time."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "guest_mode"

    def __init__(self, controller: HeatingController) -> None:
        self._controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_guest_mode"
        self._attr_device_info = system_device_info(controller)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._controller.entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def available(self) -> bool:
        return self._controller.scheduler.data is not None

    @property
    def is_on(self) -> bool:
        return self._controller.scheduler.guest_active()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        guest = self._controller.scheduler.guest()
        until = None if guest is None else guest.get("until")
        return {"until": None if until is None else dt_util.as_local(dt_util.parse_datetime(until)).isoformat()}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.scheduler.async_set_guest(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.scheduler.async_set_guest(False)
