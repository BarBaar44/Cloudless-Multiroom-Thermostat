"""TRV external temperature inputs, the thermostat's tuning numbers and the sim speed.

The tuning numbers mirror thermostat.yaml: "Central heating max flow
temperature", Kp, Ki and Kd, with the same ranges, steps and defaults, and
they keep their value over a restart. There is deliberately no writable hot
water setpoint (see the README: some boilers lock out when it is written).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTemperature

from . import DOMAIN, HeatingSim
from .entity import SimEntity
from .model import SimTrv


@dataclass(frozen=True)
class Param:
    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    get: Callable[[HeatingSim], float]
    set: Callable[[HeatingSim, float], None]
    unit: str | None = None


def _set_attr(target: str, attr: str) -> Callable[[HeatingSim, float], None]:
    def setter(sim: HeatingSim, value: float) -> None:
        setattr(sim.pid if target == "pid" else sim, attr, value)

    return setter


PARAMS = [
    Param(
        "max_flow", "Sim central heating max flow temperature", 25, 80, 0.5,
        lambda s: s.flow_limit, _set_attr("sim", "flow_limit"), UnitOfTemperature.CELSIUS,
    ),
    Param("kp", "Sim central heating Kp", 0, 6, 0.01, lambda s: s.pid.kp, _set_attr("pid", "kp")),
    Param("ki", "Sim central heating Ki", 0, 0.05, 0.0001, lambda s: s.pid.ki, _set_attr("pid", "ki")),
    Param("kd", "Sim central heating Kd", 0, 8000, 10, lambda s: s.pid.kd, _set_attr("pid", "kd")),
    # Sim seconds per real second: 1 is real time (needed for the learning features)
    Param("speed", "Sim speed", 1, 600, 1, lambda s: s.speed, _set_attr("sim", "speed")),
]


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    sim: HeatingSim = hass.data[DOMAIN]
    entities: list[NumberEntity] = [ExternalInput(trv) for room in sim.rooms for trv in room.trvs]
    entities += [SimParam(sim, p) for p in PARAMS]
    async_add_entities(entities)


class ExternalInput(SimEntity, NumberEntity):
    """External temperature input of a TRV (like Sonoff TRVZB / Shelly BLU TRV)."""

    _attr_native_min_value = -10
    _attr_native_max_value = 50
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, trv: SimTrv) -> None:
        self._trv = trv
        self._attr_name = f"Sim {trv.room.name} TRV {trv.index} external temperature"
        self._attr_unique_id = f"heating_sim_{trv.key}_external"

    @property
    def native_value(self) -> float | None:
        return self._trv.external

    async def async_set_native_value(self, value: float) -> None:
        self._trv.external = value
        self._trv.external_at = time.monotonic()
        self.async_write_ha_state()


class SimParam(SimEntity, RestoreNumber):
    """A setting of the fake thermostat, kept over a restart."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, sim: HeatingSim, param: Param) -> None:
        self._sim = sim
        self._param = param
        self._attr_name = param.name
        self._attr_unique_id = f"heating_sim_{param.key}"
        self._attr_native_min_value = param.minimum
        self._attr_native_max_value = param.maximum
        self._attr_native_step = param.step
        self._attr_native_unit_of_measurement = param.unit

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._param.set(self._sim, float(last.native_value))

    @property
    def native_value(self) -> float:
        return self._param.get(self._sim)

    async def async_set_native_value(self, value: float) -> None:
        self._param.set(self._sim, float(value))
        self.async_write_ha_state()
