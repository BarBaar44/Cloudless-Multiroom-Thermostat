# Roadmap

Where Cloudless Multiroom Thermostat is going, and in what order. Plans can change; the issues linked below hold the details and the discussion.

## The horizon

**An autonomous thermostat in every room that keeps the house comfortable at the lowest cost.**

You say when a room must be warm and how warm. Each room learns how fast it heats and cools, the integration decides when to start, how hot the boiler water needs to be and which rooms heat together, and it shows what that saved. No cloud, no tuning by hand.

Comfort comes first. Saving money never means a cold room at a time you asked for it to be warm; it means heating less, later, cooler and at the cheaper moment around that.

## Where the savings come from

In order of how much they are expected to matter on a gas boiler:

1. **Heating fewer hours:** start as late as possible and stop early enough to coast, instead of fixed switch times with margin.
2. **Cooler boiler water:** a lower flow temperature condenses better (return below about 55 °C), so more heat per m³.
3. **Fewer burner starts:** a boiler that short-cycles on a small load wastes gas and wears out faster.
4. **The cheaper moment:** with a dynamic gas tariff the price changes at 06:00; a warm-up that has to happen around then can be moved to the cheaper side. With electricity (heat pump, hybrid, electric heaters) price moves every hour and this lever grows a lot.

Every step below is measured before it is trusted: features start observe only, prove themselves against exit criteria, and only then act, with guardrails and a way back.

## v1: feature complete

v1.8.0 is the last feature release of v1. The integration does what the v1 scope set out to do: rooms, winner selection, TRV sync, windows, presence, presets, the Heating Control Card inside the integration, and learning features that observe and can apply PID advice.

### v1.8.x: small updates

Fixes and upkeep only. No new behaviour.

- Fixes from daily use and issue reports.
- Keep up with Home Assistant: deprecations, new minimum versions, the pinned test version.
- README: rewrite the Atag C1 51 section and the help text of **Boiler hot water setpoint** in plain words first (what happens, what to do), codes after.
- Card: show the `waiting` role for rooms that only heat along.

### v1.9.x: preparing v2

Everything v2 needs to know, measured now, without changing how the house heats. Each item is observe only unless it says otherwise.

- **Learning per room** ([#82](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/82), step 1): warm-up episodes and PID advice for every room, not only the room to follow. Shows whether rooms really need their own PID values before v2 builds it.
- **Cooling per room:** the night model learns each room's cooling rate, not only the followed room's. Needed to know how early each room has to start.
- **Low-load detection** ([#80](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/80), phase 1): burn and off times per warm-up, an estimate of the boiler's minimum output, and `low_load` warm-ups kept out of the `oscillating` advice so automatic PID changes don't act on them.
- **Data for the heating curve** ([#75](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/75)): prove the flow really stays at the flow limit, and collect warm-ups at one fixed limit across cold and mild mornings.
- **Return water and condensing:** record the share of each warm-up with return water below about 55 °C, so a lower flow can be judged on gas, not only on comfort.
- **Long-term statistics everywhere:** every numeric learning sensor gets a state class and a unit, so trends are kept from now on (statistics start the day this ships).
- **Boiler identity:** read the OpenTherm manufacturer code where the firmware exposes it, and check which adapters can (ESPHome, DIYLess, OTGW). Groundwork for the boiler profile.
- **Price input:** the gas prices already on the learning features page feed a cost per warm-up and per day in the records, so v2 starts with a cost history.
- **Deprecation notices:** the log and README announce what v2 removes (the 21:00 report, the report sensor, the evening notification option, `experimental_report`).

## v2: the house runs itself

A major version: presets become a list, schedules get their own storage, the card writes more than room climates, and the evening report gives way to live data. Upgrades from v1.9 keep rooms, presets and learning history.

### v2.0: schedules, live learning data, boiler profile

- **Schedules in the integration:** a week schedule per room with switch points at 15 minutes that set a preset; copy days and weeks; schedule off per room, suspend all at once. Replaces schedule automations.
- **Your own presets:** Eco and Warm plus your own (Sleep, for example), a temperature per room or "not used".
- **Manual changes that expire:** until the next switch point, 1 hour, 3 hours, or until you go back to the schedule.
- **Sun assist in the integration:** rooms that get sun hold a lower temperature on a sunny morning and warm up only if a light sensor still reads dark at the check time.
- **Live learning data:** sensors per feature that update when their value changes, an `event` entity for automatic changes and other events, and history on request for the card. The 21:00 report goes.
- **Boiler profile and known quirks:** pick the boiler make and model at setup; anything the integration would write to the boiler is checked against a list of known problems (first entry: never write the hot water temperature on an Atag E325EC). Unknown boilers have boiler writes off by default.
- **Heating Control Card:** schedule line and today strip per room, a whole house timeline, a week view, editors for schedules, presets and overrides, and a learning view.

### v2.1: warm when you need it

The step from "switch on at" to "be warm at". Built on the per room cooling and warm-up data from v1.9.

- **Comfort times:** a switch point to a warmer preset means "be at this temperature by then". The room starts as late as its learned warm-up time allows, given the outdoor temperature and how far it cooled. Off by default per room until the room has enough warm-ups; the plain switch time stays the fallback.
- **Early stop:** before a switch point to a cooler preset, stop heating when the room will coast to the end within a set margin.
- **Show it:** the card and the room attributes show the planned start and why ("starts 06:20, needs 40 min at 3 °C outside").

### v2.2: a controller per room

- **PID per room** ([#82](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/82), option B, if v1.9 shows rooms differ enough): each room calculates the flow it needs, the boiler gets the highest request, and each room's PID values are advised and applied from its own warm-ups. `thermostat.yaml` gets a flow setpoint mode with the same fail safe as today. Existing installs keep the firmware PID until they switch.
- **Buffer rooms for low load** ([#80](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/80), phase 2): an opt-in room option that heats along when the only driving room needs less than the boiler's minimum, measured on starts per hour with and without.
- **Heating curve from Home Assistant** ([#75](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/75)): the flow limit follows the outdoor temperature in fixed steps, chosen from measured warm-ups, never changed during a warm-up. With a PID per room this becomes the upper bound for every room's flow request.

### v2.3: the cheaper moment

- **Price aware starts:** when a comfort time can be met from either side of a price change, start on the cheaper side, within the comfort margin.
- **Lining up rooms:** schedules and comfort times of rooms that heat in the same hour are nudged together, so the boiler runs with more load and fewer starts.
- **Savings you can check:** a cost and gas sensor per day and per room against a baseline (degree-day corrected), so every feature above shows what it saved, or that it didn't.

## Later, not planned yet

- **Electric heat sources:** a heat pump or hybrid adapter, and electric heaters per room. This is where hourly electricity prices make price optimization worth much more than with gas.
- **Duty cycle for low load** in `thermostat.yaml` (burn at a fixed flow, then hold off longer than the anti-cycle time).
- **Learned occupancy:** suggest schedule changes from presence history; never applied without a confirm.
- **Top-up PID values:** only if the records show top-up overshoot changes with Kp and Ki (an open question from v1.6).

## How a feature gets in

1. Observe only, with records and an exit criterion written down in [docs/experimental.md](docs/experimental.md).
2. Shown on the card or in a sensor, so it can be checked in daily use.
3. Acts only when switched on, one change at a time, with a check that keeps it or reverts it.
4. Off by default until it has met its exit criterion in more than one house.

Ideas and data from your own house are welcome in the [issues](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues).
