# Reference

Every entity, attribute and service the integration creates. Entity ids follow the names you gave: `<system>` is the heating system's name, `<room>` a room's name. You can rename any entity in Home Assistant; the integration finds them by their unique id.

## Per room

Each room is a device with these entities.

| Entity | What it is |
|---|---|
| `switch.<system>_someone_is_home_guest_mode` | Guest mode: on, the house counts as occupied whatever presence says. Attribute `until`. See [Away](away.md#guest-mode) |
| `climate.<room>` | The room's virtual thermostat: Heat/Off, target, presets **Eco** and **Warm** (a target set by hand shows as **Manual**). Mode, preset and target survive a restart |
| `binary_sensor.<room>_paused` | On while the room is set to heat but held off |
| `binary_sensor.<room>_window` | Only with window sensors: open or closed after the open and close delays, as the heating sees it |

**Attributes of `climate.<room>`:**

| Attribute | Meaning |
|---|---|
| `role` | `winner`, `passenger`, `calls_for_heat`, `waiting`, `reached`, `paused` or `off`. See [Rooms](rooms.md#what-you-see-on-the-card) |
| `paused_reason` | `window`, `manual` or `away` while paused, otherwise empty |
| `manual_pause` | `true` after `pause_room`, until `resume_room` |
| `window_open` | `true` while a window counts as open |
| `effective_target` | The target actually sent to the TRVs and the heat source: the room's target, its eco temperature when away lowers rooms, or the off temperature while off or paused. The winner's TRVs get this plus the overshoot buffer |
| `is_winner` | `true` while this room drives the heat source |
| `drives_heat_source` | The room's **Drives the heat source** setting. See [Rooms](rooms.md#drives-the-heat-source) |
| `external_sensor_ignored` | `true` while a TRV external sensor select is not on its remote option and the room sensor works. See [Rooms](rooms.md#trv-external-sensor-selects) |
| `schedule_state` | `active` (follows its schedule), `none` (no schedule: holds the Temperature without schedule), `off` (scheduling off), `suspended`, `blocked` (schedule file can't be used). See [Schedules](schedules.md) |
| `next_change` | Next schedule change: `at` (local time) and `preset`, or none |
| `override` | The change by hand in force: `target`, `preset`, `until` (local time, none for until I change it) and `keep_when_away`, or none |
| `override_until` | When a change by hand ends (local time), or none |

The room's `hvac_action` is heating while it is the winner or a passenger and the heat source runs, idle otherwise, and off while it is off or paused.

**Attribute of `binary_sensor.<room>_paused`:** `reason`, the same values as `paused_reason`.

## System entities

The heating system is a device with these entities.

| Entity | What it is |
|---|---|
| `sensor.<system>_winning_room` | The name of the room that drives the heat source, or `Off` |
| `sensor.<system>_winning_room_temperature` | That room's temperature. The process value for a firmware PID such as [`thermostat.yaml`](hardware.md#esphome-opentherm-thermostat-thermostatyaml) |
| `sensor.<system>_delta_temperature_legacy` | Disabled by default. The winner as one JSON state (`area`, `target`, `curr`, `delta`) for dashboards that expect that format |

**Attributes of `sensor.<system>_winning_room`:**

| Attribute | Meaning |
|---|---|
| `area` | The winning room's area, or its name when it has none |
| `target` | The target sent to the heat source |
| `current` | The winning room's temperature |
| `delta` | Target minus temperature |
| `present` | `false` while everybody is away (see [Away](away.md)) |

**Learning features** add five sensors to the heating system when they are switched on: gas per degree-day, night prediction, last warm-up overshoot, PID advice and the learning features report. Their states and attributes are in [Learning features](experimental.md#maturity-at-a-glance). They also add diagnostic sensors with long-term statistics for the numbers worth following over a season (see [Long-term statistics](experimental.md#long-term-statistics)).

Attributes added since v1.9:

| Sensor | Attribute | Meaning |
|---|---|---|
| PID advice | `per_room` | Advice per room with enough warm-ups, observe only. See [Advice per room](experimental.md#advice-per-room) |
| Night prediction | `cooling_per_room` | Cooling time constant per room. See [Cooling per room](experimental.md#cooling-per-room) |
| Last warm-up overshoot | `return_avg`, `condensing_pct`, `gas_used`, `cost` | Per warm-up: average return, [condensing share](experimental.md#condensing-share), gas and [cost](experimental.md#cost-per-warm-up-and-per-day) |
| Learning features report | `heating_curve`, `curve`, `min_power`, `boiler_identity`, `heatup` | [Heating curve data](experimental.md#heating-curve-data), the [heating curve learned](experimental.md#heating-curve-learned), [boiler minimum power](experimental.md#low-load-detection), what the boiler reports about itself, the [heat-up model](experimental.md#heat-up-model-per-room) |

## Services

| Service | Fields | What it does |
|---|---|---|
| `cloudless_multiroom_thermostat.pause_room` | target: room climate entities | Hold a room off until resumed, keeping its mode and target |
| `cloudless_multiroom_thermostat.resume_room` | target: room climate entities | End a manual pause |
| `cloudless_multiroom_thermostat.set_all_off` | `config_entry_id` (optional) | Set every room to Off, or only the rooms of that heating system |
| `cloudless_multiroom_thermostat.set_schedule` | room climate; `week`, `scheduling` | Save a room's week schedule, or turn scheduling on or off. See [Schedules](schedules.md#actions) |
| `cloudless_multiroom_thermostat.set_override` | room climate; `temperature` or `preset`, `until` or `duration`, `keep_when_away` | A change by hand on a room with a schedule. See [Schedules](schedules.md#changes-by-hand) |
| `cloudless_multiroom_thermostat.resume_schedule` | room climate | End a change by hand: back to the schedule |
| `cloudless_multiroom_thermostat.set_guest_mode` | `on` (default true), `until` or `duration`, `config_entry_id` (optional) | Someone is home: presence is ignored until switched off or the end. See [Away](away.md#guest-mode) |
| `cloudless_multiroom_thermostat.suspend_schedules` | `config_entry_id` (optional) | Rooms with a schedule hold the Temperature without schedule |
| `cloudless_multiroom_thermostat.resume_schedules` | `config_entry_id` (optional) | Rooms follow their schedules again |
| `cloudless_multiroom_thermostat.experimental_report` | `config_entry_id` (optional) | Post the learning features report now |

The room climates also take the standard climate services: `climate.set_hvac_mode` (`heat`, `off`), `climate.set_temperature` and `climate.set_preset_mode` (`eco`, `warm`).

## Card

The integration serves the [Heating Control Card](card.md) at `/cloudless_multiroom_thermostat/heating-control-card.js` and adds it to the dashboard resources at startup. Card type: `custom:heating-control-card`.

## Files

Learning features data: `config/cloudless_multiroom_thermostat/<entry id>/`: warm-ups (`episodes.jsonl`, with the minute samples of each next to it), nights (`nights.jsonl`), gas days, heat-up model (`heatup.jsonl`), hold profile (`hold.jsonl`), heating curve (`curve.jsonl`) and state files. See [Data and privacy](experimental.md#data-and-privacy).
