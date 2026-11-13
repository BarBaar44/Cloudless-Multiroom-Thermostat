# Reference

Every entity, attribute and service the integration creates. Entity ids follow the names you gave: `<system>` is the heating system's name, `<room>` a room's name. You can rename any entity in Home Assistant; the integration finds them by their unique id.

## Per room

Each room is a device with these entities.

| Entity | What it is |
|---|---|
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

**Learning features** add five sensors to the heating system when they are switched on: gas per degree-day, night prediction, last warm-up overshoot, PID advice and the learning features report. Their states and attributes are in [Learning features](experimental.md#maturity-at-a-glance).

## Services

| Service | Fields | What it does |
|---|---|---|
| `cloudless_multiroom_thermostat.pause_room` | target: room climate entities | Hold a room off until resumed, keeping its mode and target |
| `cloudless_multiroom_thermostat.resume_room` | target: room climate entities | End a manual pause |
| `cloudless_multiroom_thermostat.set_all_off` | `config_entry_id` (optional) | Set every room to Off, or only the rooms of that heating system |
| `cloudless_multiroom_thermostat.experimental_report` | `config_entry_id` (optional) | Post the learning features report now |

The room climates also take the standard climate services: `climate.set_hvac_mode` (`heat`, `off`), `climate.set_temperature` and `climate.set_preset_mode` (`eco`, `warm`).

## Card

The integration serves the [Heating Control Card](card.md) at `/cloudless_multiroom_thermostat/heating-control-card.js` and adds it to the dashboard resources at startup. Card type: `custom:heating-control-card`.

## Files

Learning features data: `config/cloudless_multiroom_thermostat/<entry id>/`. See [Data and privacy](experimental.md#data-and-privacy).
