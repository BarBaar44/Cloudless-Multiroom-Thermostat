"""heating_sim: a fake house for testing Cloudless Multiroom Thermostat.

Creates per room a temperature sensor, N fake TRVs (climate) with an
external temperature input (number), plus a fake boiler thermostat with an
ESPHome style PID (climate), its tuning numbers, boiler sensors, a boiler
relay and a central heating enable switch. The house itself is in model.py.

Test only. Not for a real installation.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .model import House, SimRoom, SimTrv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "heating_sim"
SIGNAL = f"{DOMAIN}_tick"
PLATFORMS = [
    Platform.SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.WEATHER,
]
# Gas meter: recorder statistics run on real time, so gas is counted per real
# hour. Heating gas follows the burner output; hot water uses a fixed rate.
KWH_PER_M3 = 9.3  # 9.77 kWh per m³ at about 95 % efficiency
GAS_DHW_PER_HOUR = 1.15  # 0.019 m³ per burner minute, the rate the gas split assumes

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("start_temperature", default=17.0): vol.Coerce(float),
        vol.Optional("trvs", default=1): vol.All(int, vol.Range(min=0, max=4)),
        # Degrees per sim hour with every valve open and the flow 20 degC above the room
        vol.Optional("heat_rate", default=2.0): vol.Coerce(float),
        # Fraction of the indoor/outdoor gap lost per sim hour
        vol.Optional("loss_rate", default=0.06): vol.Coerce(float),
        # kW the room's radiators take from the water, same conditions (default 1 per TRV)
        vol.Optional("radiator_kw"): vol.Coerce(float),
        vol.Optional("window", default=None): vol.Any(None, cv.entity_id),
    }
)

BOILER_SCHEMA = vol.Schema(
    {
        vol.Optional("min_kw", default=6.1): vol.Coerce(float),
        vol.Optional("max_kw", default=24.0): vol.Coerce(float),
        vol.Optional("anti_cycle_minutes", default=5.0): vol.Coerce(float),
        # Flow temperature an on/off relay boiler runs at
        vol.Optional("relay_flow_temperature", default=55.0): vol.Coerce(float),
        # Read only, like the hot water setpoint on the boiler panel
        vol.Optional("hot_water_setpoint", default=50.0): vol.Coerce(float),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional("outdoor_temperature", default=8.0): vol.Coerce(float),
                # Sim seconds per real second at the first start; after that number.sim_speed
                vol.Optional("speed", default=30.0): vol.All(vol.Coerce(float), vol.Range(min=1, max=600)),
                vol.Optional("tick_seconds", default=5): vol.All(int, vol.Range(min=1, max=60)),
                # Extra loss per sim hour while a window is open
                vol.Optional("window_loss_rate", default=0.6): vol.Coerce(float),
                # Toggle this to simulate a shower: the burner runs for hot water
                vol.Optional("hot_water", default=None): vol.Any(None, cv.entity_id),
                # What the thermostat's PID regulates on, like sensor.virtual_heating_temperature
                vol.Optional(
                    "process_value", default="sensor.sim_heating_winning_room_temperature"
                ): cv.entity_id,
                vol.Optional("boiler", default={}): BOILER_SCHEMA,
                vol.Optional("gas_price_before_6", default=1.25): vol.Coerce(float),
                vol.Optional("gas_price_after_6", default=1.31): vol.Coerce(float),
                vol.Required("rooms"): vol.All(cv.ensure_list, [ROOM_SCHEMA]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class HeatingSim:
    """Home Assistant side of the model: reads the inputs, runs it, counts gas."""

    def __init__(self, hass: HomeAssistant, conf: dict[str, Any]) -> None:
        self.hass = hass
        self.conf = conf
        rooms: list[SimRoom] = []
        for rc in conf["rooms"]:
            room = SimRoom(
                name=rc["name"],
                key=slugify(rc["name"]),
                temperature=rc["start_temperature"],
                heat_rate=rc["heat_rate"],
                loss_rate=rc["loss_rate"],
                radiator_kw=rc.get("radiator_kw", float(max(rc["trvs"], 1))),
                window=rc["window"],
            )
            room.trvs = [SimTrv(room, i + 1) for i in range(rc["trvs"])]
            rooms.append(room)
        self.house = House(rooms, conf["outdoor_temperature"], conf["window_loss_rate"])
        bc = conf["boiler"]
        b = self.house.boiler
        b.min_kw, b.max_kw, b.anti_cycle_min = bc["min_kw"], bc["max_kw"], bc["anti_cycle_minutes"]
        b.water = b.ret = min(r.temperature for r in rooms)
        self.relay_flow = bc["relay_flow_temperature"]
        self.hot_water_setpoint = bc["hot_water_setpoint"]
        self.speed = conf["speed"]
        self.flow_limit = 40.0  # number.sim_central_heating_max_flow_temperature
        self.boiler_on = True  # the thermostat climate's mode
        self.boiler_target = 10.0
        self.relay_on = False
        self.ch_enabled = True
        self.request = 0.0  # flow temperature asked of the boiler
        self.gas_m3 = 1000.0
        self._ch_kwh_seen = 0.0
        self._last = time.monotonic()

    @property
    def rooms(self) -> list[SimRoom]:
        return self.house.rooms

    @property
    def boiler(self):
        return self.house.boiler

    @property
    def pid(self):
        return self.house.pid

    @property
    def outdoor(self) -> float:
        return self.house.outdoor

    @property
    def hot_water(self) -> bool:
        entity_id = self.conf.get("hot_water")
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state == "on"

    @property
    def flame(self) -> bool:
        return self.boiler.burner_on

    @property
    def ch_active(self) -> bool:
        """Central heating mode as OpenTherm reports it: heat asked, not making hot water."""
        return self.boiler.ch_demand

    @property
    def process_value(self) -> float | None:
        state = self.hass.states.get(self.conf["process_value"])
        try:
            return float(state.state) if state else None
        except ValueError:
            return None

    def window_open(self, room: SimRoom) -> bool:
        if not room.window:
            return False
        state = self.hass.states.get(room.window)
        return state is not None and state.state == "on"

    @callback
    def tick(self, _now: Any = None) -> None:
        now = time.monotonic()
        real_hours = (now - self._last) / 3600
        sim_hours = real_hours * self.speed
        self._last = now
        if self.relay_on:
            self.pid.update(None, None, 0)
            self.request = self.relay_flow
        else:
            if self.boiler_on:
                output = self.pid.update(self.boiler_target, self.process_value, sim_hours * 3600)
            else:
                output = self.pid.update(None, None, 0)
            self.request = round(output * self.flow_limit, 2) if self.ch_enabled else 0.0
        hot_water = self.hot_water
        windows = {r.key: self.window_open(r) for r in self.rooms}
        before = self.boiler.ch_kwh
        self.house.step(sim_hours, self.request, hot_water, now, windows)
        # Heating gas: burner energy per sim time, counted per real time
        self.gas_m3 += (self.boiler.ch_kwh - before) / self.speed / KWH_PER_M3
        if hot_water:
            self.gas_m3 += GAS_DHW_PER_HOUR * real_hours
        async_dispatcher_send(self.hass, SIGNAL)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config[DOMAIN]
    sim = HeatingSim(hass, conf)
    hass.data[DOMAIN] = sim
    for platform in PLATFORMS:
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))
    async_track_time_interval(hass, sim.tick, timedelta(seconds=conf["tick_seconds"]))
    _LOGGER.warning("heating_sim: %d fake rooms. Test only.", len(sim.rooms))
    return True
