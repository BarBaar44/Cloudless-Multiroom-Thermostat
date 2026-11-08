"""The fake house itself: rooms, TRVs, a PID thermostat and a modulating boiler.

No Home Assistant imports, so the model can be run and tried on its own
(`python3 model.py` prints a Living Room warm-up).

Time is sim time: `step()` takes sim hours. The PID works in sim seconds,
so the same Kp and Ki behave as they would in a real house at any speed.

Boiler, in short:
- The PID output (0 to 1) times the flow limit is the flow temperature the
  thermostat asks for (like `thermostat.yaml`); 0 means off.
- The burner modulates between a minimum and a maximum output. When the
  rooms take less heat than the minimum, the water overheats, the burner
  stops at the request plus `off_above`, and it can only start again after
  the anti-cycle time and once the water has dropped `restart_below` under
  the request. That is the short cycling of a too big boiler.
- Hot water (a shower) takes the burner: central heating pauses meanwhile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

# Radiator output and room heat_rate are given at a flow 20 degC above the room
DESIGN_DELTA = 20.0
WATER_MAX = 90.0
STEP_HOURS = 30 / 3600  # longest model step: 30 sim seconds


@dataclass
class SimTrv:
    room: SimRoom
    index: int
    hvac_on: bool = True
    target: float = 15.0
    external: float | None = None
    external_at: float = -1e9  # real time.monotonic() of the last external input

    @property
    def key(self) -> str:
        return f"{self.room.key}_trv_{self.index}"

    def measured(self, now: float) -> float:
        """What the TRV thinks the room is: external input if recent, else its own warm sensor."""
        if self.external is not None and now - self.external_at < 2 * 3600:
            return self.external
        return self.room.temperature + 1.5  # sits on the radiator, reads warm

    def valve_open(self, now: float) -> bool:
        return self.hvac_on and self.target > self.measured(now)


@dataclass
class SimRoom:
    name: str
    key: str
    temperature: float
    heat_rate: float  # degC per sim hour, all valves open, flow 20 degC above the room
    loss_rate: float  # share of the indoor/outdoor gap lost per sim hour
    radiator_kw: float  # heat the room takes from the water, same conditions
    window: str | None = None
    trvs: list[SimTrv] = field(default_factory=list)

    def opening(self, now: float) -> float:
        """Share of this room's radiators that is open (rooms without TRVs heat freely)."""
        if not self.trvs:
            return 1.0
        return sum(1 for t in self.trvs if t.valve_open(now)) / len(self.trvs)


@dataclass
class Pid:
    """ESPHome climate.pid, heat only, with `min_integral: 0` like thermostat.yaml."""

    kp: float = 1.75
    ki: float = 0.0075
    kd: float = 0.0
    min_integral: float = 0.0
    max_integral: float = 1.0
    proportional: float = 0.0
    integral: float = 0.0
    derivative: float = 0.0
    output: float = 0.0
    _last_error: float | None = None

    def update(self, target: float | None, value: float | None, dt_s: float) -> float:
        """One update over dt_s sim seconds; no reading (NaN) means output 0, like the fail safe."""
        if target is None or value is None or math.isnan(value) or dt_s <= 0:
            self._last_error = None
            self.proportional = self.derivative = self.output = 0.0
            return 0.0
        error = target - value
        self.proportional = self.kp * error
        self.integral = min(max(self.integral + self.ki * error * dt_s, self.min_integral), self.max_integral)
        if self._last_error is None:
            self.derivative = 0.0
        else:
            self.derivative = self.kd * (error - self._last_error) / dt_s
        self._last_error = error
        self.output = min(max(self.proportional + self.integral + self.derivative, 0.0), 1.0)
        return self.output


@dataclass
class Boiler:
    min_kw: float = 6.1
    max_kw: float = 24.0
    anti_cycle_min: float = 5.0
    off_above: float = 5.0
    restart_below: float = 3.0
    water_kwh_per_degree: float = 0.08  # system water and boiler metal
    flow_lph: float = 600.0  # pump flow, sets the flow/return difference
    hot_water_flow: float = 60.0  # primary water temperature while making hot water
    water: float = 20.0
    ret: float = 20.0
    burner_on: bool = False
    burner_kw: float = 0.0
    on_dhw: bool = False
    ch_demand: bool = False
    load_kw: float = 0.0
    starts: int = 0
    ch_kwh: float = 0.0  # burner energy for heating, sim time
    clock_h: float = 0.0
    _off_at_h: float = -1.0

    @property
    def modulation(self) -> float:
        """Burner output as % of the maximum, like OpenTherm relative modulation."""
        return round(100 * self.burner_kw / self.max_kw, 1) if self.burner_on else 0.0

    def step(self, hours: float, request: float, hot_water: bool, rooms: list[SimRoom], now: float, ambient: float) -> None:
        """Advance the water temperature, burner and rooms by `hours` sim hours."""
        c = self.water_kwh_per_degree
        self.clock_h += hours
        self.on_dhw = hot_water
        self.ch_demand = request > 0 and not hot_water
        if hot_water:
            if not self.burner_on:
                self.starts += 1
            self.burner_on, self.burner_kw, self.load_kw = True, self.max_kw, 0.0
            self.water += (self.hot_water_flow - self.water) * min(1.0, hours * 6)
            self.ret = self.water
            return
        self.load_kw = sum(
            r.radiator_kw * r.opening(now) * max(0.0, self.water - r.temperature) / DESIGN_DELTA
            for r in rooms
        ) if self.ch_demand else 0.0
        if self.burner_on and (not self.ch_demand or self.water >= request + self.off_above):
            self.burner_on, self.burner_kw, self._off_at_h = False, 0.0, self.clock_h
        elif (
            not self.burner_on
            and self.ch_demand
            and self.water <= request - self.restart_below
            and (self.clock_h - self._off_at_h) * 60 >= self.anti_cycle_min
        ):
            self.burner_on = True
            self.starts += 1
        if self.burner_on:
            # Aim at the request within a few minutes, inside the modulation range
            wanted = self.load_kw + c * (request - self.water) / 0.05
            self.burner_kw = min(max(wanted, self.min_kw), self.max_kw)
        if self.ch_demand:
            self.ch_kwh += self.burner_kw * hours
            self.water += (self.burner_kw - self.load_kw) / c * hours
        else:
            # Pump off: the water cools slowly where it stands
            self.water -= (self.water - ambient) * 0.5 * hours
        self.water = min(max(self.water, ambient), WATER_MAX)
        self.ret = self.water - self.load_kw * 860 / self.flow_lph if self.ch_demand else self.water
        self.ret = max(self.ret, ambient)


class House:
    """Rooms, boiler and PID, advanced together."""

    def __init__(self, rooms: list[SimRoom], outdoor: float, window_loss_rate: float = 0.6) -> None:
        self.rooms = rooms
        self.outdoor = outdoor
        self.window_loss_rate = window_loss_rate
        self.boiler = Boiler()
        self.pid = Pid()

    def step(
        self,
        hours: float,
        request: float,
        hot_water: bool,
        now: float,
        windows: dict[str, bool] | None = None,
    ) -> None:
        """Advance `hours` sim hours in model steps of at most 30 sim seconds."""
        windows = windows or {}
        ambient = min((r.temperature for r in self.rooms), default=18.0)
        while hours > 1e-9:
            dt = min(hours, STEP_HOURS)
            hours -= dt
            b = self.boiler
            b.step(dt, request, hot_water, self.rooms, now, ambient)
            heating = b.ch_demand
            for room in self.rooms:
                loss = room.loss_rate + (self.window_loss_rate if windows.get(room.key) else 0.0)
                gain = 0.0
                if heating:
                    gain = room.heat_rate * room.opening(now) * max(0.0, b.water - room.temperature) / DESIGN_DELTA
                room.temperature += (gain - loss * (room.temperature - self.outdoor)) * dt
        for room in self.rooms:
            room.temperature = round(room.temperature, 3)


def _demo() -> None:
    """Living Room warm-up with the thermostat.yaml defaults, printed every 10 sim minutes."""
    room = SimRoom("Living Room", "living_room", 17.5, 1.5, 0.06, 3.0)
    room.trvs = [SimTrv(room, i + 1, target=20.0) for i in range(3)]
    house = House([room], outdoor=5.0)
    house.boiler.water = 25.0
    target, limit, minute = 19.0, 40.0, 0
    print("min  room  water  ret  request  burner kW  starts")
    while minute <= 300:
        for trv in room.trvs:  # the integration pushes the room temperature to the TRVs
            trv.external, trv.external_at = room.temperature, 0.0
        output = house.pid.update(target, round(room.temperature, 1), 60)
        request = output * limit
        house.step(1 / 60, request, False, 0.0)
        if minute % 10 == 0:
            b = house.boiler
            print(f"{minute:3d}  {room.temperature:5.2f}  {b.water:5.1f}  {b.ret:4.1f}  {request:6.1f}  {b.burner_kw:6.1f}  {b.starts:4d}")
        minute += 1


if __name__ == "__main__":
    _demo()
