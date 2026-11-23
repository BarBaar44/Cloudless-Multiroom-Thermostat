# Schedules

**In one sentence:** every room follows its own week schedule of presets, run by the integration itself, so the heating keeps to it with no dashboard or automation open.

## When you want it

Always: from v2.0 every room has a schedule, or you turn scheduling off for a room you control yourself. A room with neither holds the **Temperature without schedule** (15 °C) until you choose.

## How to turn it on

- **New rooms:** the last step of **Add room** asks how the room starts: one preset all day (Eco by default), or scheduling off.
- **Rooms you already had:** they have no schedule after the upgrade and hold 15 °C. **Settings > Repairs** lists them. Give each one a schedule with the `set_schedule` action (the schedule editor in the Heating Control Card comes later in v2.0), or turn scheduling off for it.

## Settings

| Setting | Where | Default | What it does |
|---|---|---|---|
| Temperature without schedule | Heating system settings | 15 °C | Held by a room without a schedule, and by every room with a schedule while schedules are suspended |

A schedule is a week, Monday first. Each day has up to 12 switch points on 15 minute steps; each sets a preset (Eco, Warm, or Off) and holds until the next one, also over midnight and over days without points.

## How a room behaves

| The room | What it does |
|---|---|
| Has a schedule | Follows it. A target or preset set by hand lasts until the next schedule change (the next switch point to another preset; with one preset all day, until midnight) |
| Has no schedule | Holds the Temperature without schedule. Setting a target or preset is refused with "has no schedule: make one or turn scheduling off" |
| Scheduling off | Yours: presets, targets and your own automations work as before v2, nothing expires |
| Schedules suspended | Rooms with a schedule hold the Temperature without schedule; rooms with scheduling off are not affected. A change by hand starts that one room's schedule again, with the change on top, until schedules are resumed |

**Off is off:** a room switched off stays off whatever its schedule says. Switch it back to heat and it does what the schedule says at that moment. A switch point to **Off** is different: the room stays on heat and holds the off temperature until the next point.

Away, windows and pauses work on top of the schedule, as before. The schedule keeps running underneath, so coming home or closing a window gives what the schedule says now.

## Common questions

**Why does my room say it has no schedule?** It was there before v2.0, or the schedule file could not be read (Repairs then says why). Make a schedule, or turn scheduling off for it.

**My automation stopped changing a room.** It sets a target on a room without a schedule; the automation trace shows the error. Give the room a schedule (the automation's change then lasts until the next schedule change) or turn scheduling off for it.

**What happens on daylight saving days?** Switch points are in local time. A point in the hour that is skipped in spring happens at the jump; a point in the hour that repeats in autumn happens once.

## Actions

| Action | Target | Fields |
|---|---|---|
| `cloudless_multiroom_thermostat.set_schedule` | a room climate | `week`: seven lists of `{time, preset}`, Monday first. `scheduling`: `on` (default) or `off`. Without `week`, turning on uses the schedule the room already had |
| `cloudless_multiroom_thermostat.resume_schedule` | a room climate | Ends a change by hand: back to the schedule |
| `cloudless_multiroom_thermostat.suspend_schedules` | optional heating system | Every room with a schedule holds the Temperature without schedule; a change by hand starts that room's schedule again |
| `cloudless_multiroom_thermostat.resume_schedules` | optional heating system | Rooms follow their schedules again |

Example, Warm from 07:00 to 22:00 every day:

```yaml
action: cloudless_multiroom_thermostat.set_schedule
target:
  entity_id: climate.living_room
data:
  week:
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
    - [{time: "07:00", preset: warm}, {time: "22:00", preset: eco}]
```

## Technical detail

Room climate attributes: `schedule_state` (`active`, `none`, `off`, `suspended`, `blocked`), `next_change` (`at`, local time, and `preset`), `override_until`. Schedules, preset temperatures and overrides are kept in `.storage/cloudless_multiroom_thermostat.schedule.<entry_id>`, versioned: a copy `<file>.v<N>.bak` is made before every migration, and a file written by a newer version is never overwritten (`blocked`: every room holds the Temperature without schedule, Repairs says why).
