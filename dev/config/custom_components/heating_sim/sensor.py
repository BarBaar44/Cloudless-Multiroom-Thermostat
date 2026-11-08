"""Room, outdoor and boiler sensors, gas meter and gas prices."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature

from . import DOMAIN, HeatingSim
from .entity import SimEntity
from .model import SimRoom


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    sim: HeatingSim = hass.data[DOMAIN]
    temp = (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS)
    async_add_entities(
        [RoomTemperature(room) for room in sim.rooms]
        + [
            SimValue(sim, "outdoor_temperature", "Sim outdoor temperature", lambda s: s.outdoor, *temp),
            # Like OpenTherm t_boiler and t_ret
            SimValue(sim, "water_temperature", "Sim boiler water temperature", lambda s: round(s.boiler.water, 1), *temp),
            SimValue(sim, "return_temperature", "Sim boiler return water temperature", lambda s: round(s.boiler.ret, 1), *temp),
            # What the thermostat asks of the boiler (t_set): PID output x flow limit
            SimValue(sim, "flow_request", "Sim boiler flow request", lambda s: s.request, *temp),
            # Read only on purpose, like OpenTherm t_dhw_set
            SimValue(sim, "hot_water_setpoint", "Sim boiler hot water setpoint", lambda s: s.hot_water_setpoint, *temp),
            SimValue(sim, "modulation", "Sim boiler relative modulation", lambda s: s.boiler.modulation, None, PERCENTAGE),
            SimValue(sim, "burner_power", "Sim boiler burner power", lambda s: round(s.boiler.burner_kw, 2), SensorDeviceClass.POWER, UnitOfPower.KILO_WATT),
            # ESPHome reports the PID terms x100
            SimValue(sim, "pid_result", "Sim central heating PID result", lambda s: round(s.pid.output * 100, 2), None, PERCENTAGE),
            SimValue(sim, "pid_integral", "Sim central heating PID integral", lambda s: round(s.pid.integral * 100, 2), None, PERCENTAGE),
            BurnerStarts(sim),
            GasMeter(sim),
            SimValue(sim, "gas_price_before_6", "Sim gas price tomorrow before 6", lambda s: s.conf["gas_price_before_6"], None, "EUR/m³"),
            SimValue(sim, "gas_price_after_6", "Sim gas price tomorrow after 6", lambda s: s.conf["gas_price_after_6"], None, "EUR/m³"),
        ]
    )


class RoomTemperature(SimEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, room: SimRoom) -> None:
        self._room = room
        self._attr_name = f"Sim {room.name} temperature"
        self._attr_unique_id = f"heating_sim_{room.key}_temperature"

    @property
    def native_value(self) -> float:
        return round(self._room.temperature, 1)


class SimValue(SimEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        sim: HeatingSim,
        key: str,
        name: str,
        value: Callable[[HeatingSim], float],
        device_class: SensorDeviceClass | None,
        unit: str | None,
    ) -> None:
        self._sim = sim
        self._value = value
        self._attr_name = name
        self._attr_unique_id = f"heating_sim_{key}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float:
        return self._value(self._sim)


class BurnerStarts(SimEntity, SensorEntity):
    """Burner starts since HA started: short cycling shows here."""

    _attr_name = "Sim boiler burner starts"
    _attr_unique_id = "heating_sim_burner_starts"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, sim: HeatingSim) -> None:
        self._sim = sim

    @property
    def native_value(self) -> int:
        return self._sim.boiler.starts


class GasMeter(SimEntity, SensorEntity):
    """Total gas meter, like a P1 meter: grows while the burner runs."""

    _attr_name = "Sim gas meter"
    _attr_unique_id = "heating_sim_gas"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    _attr_suggested_display_precision = 3

    def __init__(self, sim: HeatingSim) -> None:
        self._sim = sim

    @property
    def native_value(self) -> float:
        return round(self._sim.gas_m3, 3)
