"""Shared device info helpers."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .controller import HeatingController, Room

MANUFACTURER = "Cloudless Multiroom Thermostat"


def room_device_info(controller: HeatingController, room: Room) -> DeviceInfo:
    """One device per room; the user puts it in an area from the device page."""
    return DeviceInfo(
        identifiers={(DOMAIN, room.room_id)},
        name=room.name,
        manufacturer=MANUFACTURER,
        model="Room",
        via_device_id=controller.system_device_id,
    )


def system_device_info(controller: HeatingController) -> DeviceInfo:
    """The heating system itself (winner, process value)."""
    return DeviceInfo(
        identifiers={(DOMAIN, controller.entry.entry_id)},
        name=controller.entry.title,
        manufacturer=MANUFACTURER,
        model="Heating system",
    )


def remove_entity(hass: HomeAssistant, platform: str, unique_id: str) -> None:
    """A feature that is off has no entities (#120): remove what an earlier start left behind."""
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id(platform, DOMAIN, unique_id):
        registry.async_remove(entity_id)

