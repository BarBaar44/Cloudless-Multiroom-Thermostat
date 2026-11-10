# Roadmap

Where Cloudless Multiroom Thermostat is going, and in what order. Plans can change; the issues linked below hold the details and the discussion.

## The horizon

**An autonomous thermostat in every room that keeps the house comfortable at the lowest cost, local first and under your control.**

You say when a room must be warm and how warm. Each room learns how fast it heats and cools, the integration decides when to start, how hot the water needs to be, which rooms heat together and, later, whether gas or electricity is cheaper right now. It shows what that saved. No cloud, no tuning by hand.

Comfort comes first. Saving money never means a cold room at a time you asked for it to be warm; it means heating less, later, cooler and at the cheaper moment around that.

## Principles

- **Local first.** The integration itself runs in Home Assistant and never needs a vendor account or an internet connection. Local control is the setup it is designed, tested and documented for. Devices that can only be reached through a vendor cloud are supported where Home Assistant can control them, but the integration says plainly what depends on that cloud and what happens when it is gone: heating falls back to a safe state, and features that need fast or frequent control may be limited.
- **Nobody can take it away.** The integration has no account, no subscription and no feature that a company can move behind a paywall, change or switch off from a distance. The code is open, your learning data stays in files in your own Home Assistant, and a release you run keeps working the way it did the day you installed it. A heating system is part of the house; it should outlive any company's business model. That is why local control is recommended for every device it talks to.
- **You own the controller.** The integration is built for a thermostat you run yourself: an OpenTherm controller such as DIYLess or an ESPHome build of [`thermostat.yaml`](thermostat.yaml). The room thermostat on the wall goes; the boiler (and later the heat pump) gets its setpoint from a controller you can read, change and flash. This is what makes per room control, learning and price optimization possible, and it is the setup the docs and the test environment are written for first.
- **For people who like to tinker.** Settings are explained in plain words, but the audience builds its own hardware, reads logs and wants to know why the heating does what it does. Every decision is visible in a sensor or attribute.
- **Easy to start.** A heat source, your rooms and a schedule: that is all you need on day one. Everything else is a switch on one Features page, and a feature that is off really disappears: no settings, no entities, nothing on the card. Every feature has its own docs page in plain words.
- **Measured before trusted.** Features start observe only, prove themselves against exit criteria, and only then act, with guardrails and a way back. See [How a feature gets in](#how-a-feature-gets-in).
- **Safe for the hardware.** Nothing is written to a boiler or heat pump that is known to break it, and a lost connection to Home Assistant always ends in heating off, never in heating on.

## Where the savings come from

In order of how much they are expected to matter, starting with a gas boiler:

1. **Heating fewer hours:** start as late as possible and stop early enough to coast, instead of fixed switch times with margin.
2. **Cooler water:** a lower flow temperature costs less for the same heat. A boiler condenses better (return below about 55 °C), a heat pump gets a much higher COP. This is the lever that grows most when a heat pump arrives.
3. **Fewer starts:** a boiler or heat pump that short-cycles on a small load wastes energy and wears out faster.
4. **The cheaper source and moment:** with a hybrid, choose gas or electricity hour by hour; with any heat pump, heat ahead when electricity is cheap and let the house coast. With gas alone this lever is small (the dynamic gas price changes once a day, at 06:00).

## v1: feature complete

v1.8.0 is the last feature release of v1. The integration does what the v1 scope set out to do: rooms, winner selection, TRV sync, windows, presence, presets, the Heating Control Card inside the integration, and learning features that observe and can apply PID advice.

### v1.8.x: small updates

Fixes and upkeep only. No new behaviour.

- Fixes from daily use and issue reports.
- Keep up with Home Assistant: deprecations, new minimum versions, the pinned test version.
- README: rewrite the Atag C1 51 section and the help text of **Boiler hot water setpoint** in plain words first (what happens, what to do), codes after.
- README: put the self-run OpenTherm controller up front as the recommended setup, with DIYLess and `thermostat.yaml` as the two ready paths, and say plainly what you lose with a target only heat source.
- Card: show the `waiting` role for rooms that only heat along.

### v1.9.x: preparing v2

Everything v2 needs to know, measured now, without changing how the house heats. Each item is observe only unless it says otherwise.

- **Learning per room** ([#82](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/82), step 1): warm-up episodes and PID advice for every room, not only the room to follow. Shows whether rooms really need their own PID values before v2 builds it.
- **Cooling per room:** the night model learns each room's cooling rate, not only the followed room's. Needed to know how early each room has to start, and later how long the house can coast on cheap heat.
- **Low-load detection** ([#80](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/80), phase 1): burn and off times per warm-up, an estimate of the boiler's minimum output, and `low_load` warm-ups kept out of the `oscillating` advice so automatic PID changes don't act on them.
- **Data for the heating curve** ([#75](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/75)): prove the flow really stays at the flow limit, and collect warm-ups at one fixed limit across cold and mild mornings.
- **Return water and condensing:** record the share of each warm-up with return water below about 55 °C, so a lower flow can be judged on gas, not only on comfort.
- **Long-term statistics everywhere:** every numeric learning sensor gets a state class and a unit, so trends are kept from now on (statistics start the day this ships).
- **Boiler identity:** read the OpenTherm manufacturer code where the firmware exposes it, and check which adapters can (ESPHome, DIYLess, OTGW). Groundwork for the boiler profile.
- **DIYLess on par with `thermostat.yaml`:** check which DIYLess firmware features (flow setpoint, flow limit, room temperature as process value, fail safe) match what the ESPHome config does, document the gaps, and test both in the simulated house.
- **Cost per warm-up:** the gas prices already on the learning features page feed a cost per warm-up and per day in the records, so v2 starts with a cost history.
- **Docs you can read:** the README shrinks to what it is, why, install and running in 10 minutes. Everything else moves to one page per feature in `docs/`, all with the same layout (in one sentence, when you want it, how to turn it on, settings, what you see on the card, common questions), plus getting started, hardware, upgrading, troubleshooting and a reference of every entity and service.
- **Deprecation notices:** the log and README announce what v2 removes (the 21:00 report, the report sensor, the evening notification option, `experimental_report`).

## v2: the house runs itself

A major version: presets become a list, schedules get their own storage, the card writes more than room climates, and the evening report gives way to live data. Upgrades from v1.9 keep rooms, presets and learning history.

### v2.0: schedules, presets, live learning data

- **Schedules in the integration:** a week schedule per room with switch points at 15 minutes that set a preset; copy days and weeks; schedule off per room, suspend all at once. Replaces schedule automations.
- **Features page:** one options page with a switch per feature (away, windows, sun assist, guest mode, learning features). Off means gone.
- **Every room gets a schedule:** Add room ends with a schedule step (one block for the whole day, or scheduling off), so a new room is ready straight away. As a safety net, a room without one holds 15 °C and the card says so clearly, with two choices: make a schedule (one block is enough) or turn scheduling off and control the room yourself. Upgrading from v1 is a behaviour change, and the release notes say so first.
- **Your own presets:** Eco and Warm plus your own (Sleep, for example), a temperature per room or "not used".
- **Manual changes that expire:** until the next switch point, 1 hour, 3 hours, or until you go back to the schedule. Dropped when everyone leaves, unless you tick "keep when away".
- **Guest mode:** "someone is home" for visitors Home Assistant doesn't track, so the whole house keeps its schedule.
- **Sun assist in the integration:** rooms that get sun hold a lower temperature on a sunny morning (a window you set, 05:00 to 12:00 by default) and warm up only if a light sensor still reads dark at the check time.
- **Live learning data:** sensors per feature that update when their value changes, an `event` entity for automatic changes and other events, and history on request for the card. The 21:00 report goes.
- **Heating Control Card:** schedule line and today strip per room, a whole house timeline, a week view, editors for schedules, presets and overrides, and a learning view.

### v2.1: warm when you need it

The step from "switch on at" to "be warm at". Built on the per room cooling and warm-up data from v1.9.

- **Comfort times:** a switch point to a warmer preset means "be at this temperature by then". The room starts as late as its learned warm-up time allows, given the outdoor temperature and how far it cooled. Off by default per room until the room has enough warm-ups; the plain switch time stays the fallback.
- **Early stop:** before a switch point to a cooler preset, stop heating when the room will coast to the end within a set margin.
- **Show it:** the card and the room attributes show the planned start and why ("starts 06:20, needs 40 min at 3 °C outside").

### v2.2: a controller per room, cooler water, a safe boiler

- **PID per room** ([#82](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/82), option B, if v1.9 shows rooms differ enough): each room calculates the flow it needs, the heat source gets the highest request, and each room's PID values are advised and applied from its own warm-ups. `thermostat.yaml` and DIYLess get a flow setpoint mode with the same fail safe as today. Existing installs keep the firmware PID until they switch. This is also the base for v3: the integration knows each room's demand, not only who wins.
- **Heating curve from Home Assistant** ([#75](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/75)): the flow limit follows the outdoor temperature in fixed steps, chosen from measured warm-ups, never changed during a warm-up. With a PID per room it is the upper bound for every room's flow request.
- **Lowest flow that still meets comfort:** with comfort times known, the flow limit is lowered on mornings with time to spare, and judged on gas per degree-day, not only on comfort.
- **Boiler profile and known quirks:** pick the boiler make and model at setup (a suggestion from the boiler's own OpenTherm code where it can be read, always confirmed by you); anything the integration would write to the boiler is checked against a list of known problems (first entry: never write the hot water temperature on an Atag E325EC). Unknown boilers have boiler writes off by default. It arrives here, with the first thing the integration writes to the boiler.
- **Buffer rooms for low load** ([#80](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/80), phase 2): an opt-in room option that heats along when the only driving room needs less than the boiler's minimum, measured on starts per hour with and without.

### v2.3: the cheaper moment on gas

- **Price aware starts:** when a comfort time can be met from either side of the 06:00 gas price change, start on the cheaper side, within the comfort margin.
- **Lining up rooms:** schedules and comfort times of rooms that heat in the same hour are nudged together, so the boiler runs with more load and fewer starts.
- **Savings you can check:** a cost and energy sensor per day and per room against a baseline (degree-day corrected), so every feature above shows what it saved, or that it didn't.

## v3: hybrid heat pump, local and controllable

In the Netherlands a heat pump next to the boiler is set to become the norm when a boiler is replaced (planned from 2029, not law yet). The boiler stays, so this is where most users of this integration are heading. v3 makes the integration the local brain of a hybrid system.

- **Local control first.** Heat pumps that Home Assistant can read and control locally (OpenTherm, Modbus, a local API, or an ESPHome or similar module on the unit's own bus) get the full feature set and are what v3 is built and tested on. Units controlled through a vendor cloud are supported too, with an honest note on what that costs: slower or rate limited control, and less optimization when the cloud is slow or down. The docs list known working units and how they connect, from user reports.
- **A heat source with a cost model.** Each source knows what a kWh of heat costs right now: gas price over boiler efficiency, electricity price over the heat pump's COP at the current outdoor and flow temperature. The COP is learned from measured power and heat where meters exist, a default curve otherwise.
- **Choose the source hour by hour:** heat pump, boiler or both, by cost, within what the heat pump can deliver at that outdoor temperature. The boiler takes over below the heat pump's limit and for hot water.
- **Heat ahead on cheap electricity:** with hourly prices and solar surplus, warm the house a little above target while power is cheap and let it coast, within a comfort band you set per room. Built on the per room cooling model.
- **Heat pump friendly control:** long runs at a low flow instead of short bursts; minimum run and off times respected; valves of rooms with demand kept open.
- **Safe defaults:** the same quirks list as the boiler profile, extended to heat pumps; anything unknown starts in observe only.
- **Works next to the official requirements:** the heat pump has to meet the smart heat pump standard (NTA 8171) on its own. The integration never replaces that; it is the local layer on top that you control.

## v4: all-electric

For houses without gas, and the house this integration ends up in once the boiler goes.

- **Room balancing instead of a winner:** with a heat pump as the only source, rooms with demand are kept open and in balance at the lowest flow that meets every room, instead of one room driving and the rest throttled.
- **Cooling:** the same rooms, schedules and comfort band in summer for heat pumps that cool.
- **Hot water by price:** heat the tank when electricity is cheapest, with a minimum temperature and the legionella cycle kept.
- **Home energy coordination:** take part in a local energy plan with a home battery, solar and an EV charger (through Home Assistant's own energy data), without a vendor cloud.

## Later, not planned yet

- **Duty cycle for low load** in `thermostat.yaml` (burn at a fixed flow, then hold off longer than the anti-cycle time).
- **Electric heaters per room** as a heat source of their own, for rooms a heat pump can't reach well.
- **Sun based window for sun assist:** from sunrise to before solar noon instead of fixed times, for advanced users.
- **Learned occupancy:** suggest schedule changes from presence history; never applied without a confirm.
- **Top-up PID values:** only if the records show top-up overshoot changes with Kp and Ki (an open question from v1.6).

## How a feature gets in

1. Observe only, with records and an exit criterion written down in [docs/experimental.md](docs/experimental.md).
2. Shown on the card or in a sensor, so it can be checked in daily use.
3. Acts only when switched on, one change at a time, with a check that keeps it or reverts it.
4. Off by default until it has met its exit criterion in more than one house.

Ideas and data from your own house are welcome in the [issues](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues), especially which boilers, heat pumps and OpenTherm controllers you run and how they can be controlled locally.
