# Sun assist

**In one sentence:** on a sunny morning, rooms that get sun wait for the sun instead of warming up, unless it is still dark at the check.

## When you want it

In rooms with big windows on the east or south, where the morning sun warms the room for free. Heating them at 07:00 and then overshooting at 10:00 costs gas and comfort.

## How to turn it on

**Settings > Devices & services > Cloudless Multiroom Thermostat > Configure > Features**: switch on **Sun assist**. The next page asks for its settings; later they are under **Configure > Sun assist**. The settings live here only, never in the card.

## Settings

| Setting | Default | What it does |
|---|---|---|
| Weather forecast | | A weather entity. Its hourly forecast from the switch point to the check decides: sunny when at least half of those hours count as sunny |
| Counts as sunny | Sunny, Partly cloudy | Forecast conditions that count as sunny |
| Rooms that get sun | none | Only these rooms wait for the sun |
| Hold temperature | 15 °C | Held instead of the preset while waiting. Presets at or below it are not affected |
| Morning window | 05:00 to 12:00 | Only switch points inside it wait |
| Lux sensor | none | Optional. Without it sun assist trusts the forecast only, which is weaker |
| Still dark below | 1000 lx | At the check the preset starts when the lux sensor reads less (or can't be read) |
| Check after | 180 min | Time after the switch point when the lux sensor is checked |

## How it works

1. A switch point inside the morning window sets a preset warmer than the hold temperature, in a room that gets sun (for example Warm at 07:00).
2. The forecast is read. Sunny: the room holds the hold temperature. Not sunny, or no forecast: the preset starts as scheduled.
3. With a lux sensor, at the check time (10:00 in this example): still dark, the preset starts; bright, the room keeps waiting for the sun.
4. The next switch point ends it.

A change by hand always wins, and so do away, windows and pauses.

## What you see on the card

The room shows that its preset waits, and when it checks: *Sun assist · Warm waits, checks 10:00*.

## Common questions

**Why doesn't my room wait on a sunny morning?** Check that it is in Rooms that get sun, that the switch point is inside the morning window and its preset is warmer than the hold temperature, and that the weather entity gives an hourly forecast (otherwise its daily forecast, then its current state is used).

**Why did it warm up anyway at the check?** The lux sensor read less than Still dark below, or couldn't be read.

## Technical detail

Room climate attribute `sun_assist`: `status` (`pending` while the forecast is read, `holding`), `hold` and `check_at` (local time), or none. Decisions are kept per room and switch point in the schedule file, so a restart during a hold keeps it.
