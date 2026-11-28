# Thermostat requirements

What the integration needs from the thermostat that drives your boiler, what each part gains you, and how to build it into your own ESPHome config.

**In one sentence:** for full multi-room control the thermostat must regulate on the integration's **Winning room temperature** and accept the winner's target; everything else on this page makes the learning features work, or makes the heating safer.

**Preferred:** a [DIYLess OpenTherm thermostat](https://diyless.com/product/opentherm-thermostat) running ESPHome with [`thermostat.yaml`](../thermostat.yaml). It is what the integration is built and tested on, and it covers every row below. Other thermostats are welcome; [Other thermostats](#other-thermostats) says what each one can and can't do.

## Capabilities

**Direction:** *read* means the integration only reads the entity; *write* means it sets it. **Level:** *required* for full multi-room control, *recommended* for the learning features, *optional* for extra detail.

### Heat source

| Capability | Direction | Level | Integration field or feature | Without it | In `thermostat.yaml` |
|---|---|---|---|---|---|
| Climate entity that accepts a target temperature and hvac mode | write | required | **Heat source** (type Climate entity) | No boiler control | `climate: platform: pid` (`main_climate`) |
| Regulates on the **Winning room temperature** sensor, not on a sensor of its own | read (by the thermostat) | required | Every room can start the boiler | *Target only*: the boiler follows the room where the thermostat hangs | `sensor: platform: homeassistant` with a 1 s heartbeat, used as the PID's `sensor` |
| Modulating flow request to the boiler, 0 means boiler off | inside the thermostat | required | Gentle low flow heating | On and off only: use the On/off switch heat source instead | `output:` `t_set` (0 to 100 °C, `zero_means_zero`) driven by the PID through `ch_flow_request` |
| Stops heating when Home Assistant is gone | inside the thermostat | required | Safety | Keeps heating towards the last target on a frozen temperature | `interval:` fail safe (5 minutes without the API: room temperature unknown, PID output off) |
| Central heating enable switch | write | optional | **Central heating enable switch** | The boiler's CH enable stays as the thermostat sets it | `switch: platform: opentherm` `ch_enable` |

### Flow limit and PID

| Capability | Direction | Level | Integration field or feature | Without it | In `thermostat.yaml` |
|---|---|---|---|---|---|
| Flow limit as a number entity | read | recommended | **Boiler maximum flow temperature**: warm-ups with another limit kept apart, PID advice limits scale with it, [heating curve data](experimental.md#heating-curve-data) | Warm-ups at different limits are compared as if equal | `number:` `max_flow` (Central heating max flow temperature) |
| Kp, Ki and Kd as number entities, applied at boot and on change | read; write only with **Apply PID advice automatically** | recommended | **PID Kp / Ki / Kd**: PID advice | No PID advice | `number:` `main_kp`, `main_ki`, `main_kd` and the `apply_pid_params` script |
| Integral never below 0 | inside the thermostat | recommended | Faster mornings | The integral sinks overnight and has to unwind every morning | `climate:` `min_integral: 0` |
| Requested flow temperature sensor | read | recommended | **Requested flow temperature**: [heating curve data](experimental.md#heating-curve-data), [low-load detection](experimental.md#low-load-detection) | Low-load detection falls back to the flow limit and misses cycling below it | `sensor: platform: template` `flow_request`, published by `ch_flow_request` |
| PID integral sensor | read | optional | **PID integral** | Less detail in the report | `sensor: platform: pid` `INTEGRAL` |

### Boiler telemetry

| Capability | Direction | Level | Integration field or feature | Without it | In `thermostat.yaml` |
|---|---|---|---|---|---|
| Flame on, hot water active, central heating active | read | recommended | **Burner flame**, **Hot water active**, **Central heating active**: hot water split, warm-up flame starts, low-load detection | No hot water split, no flame starts | `binary_sensor: platform: opentherm` `flame_on`, `dhw_active`, `ch_active` |
| Flow water temperature | read | recommended | **Flow water temperature**: warm-up records, heating curve data | No flow data per warm-up | `sensor: platform: opentherm` `t_boiler` |
| Return water temperature | read | recommended | **Return water temperature**: [condensing share](experimental.md#condensing-share) | No condensing share | `sensor: platform: opentherm` `t_ret` |
| Hot water setpoint as a **read only** sensor | read | optional | **Boiler hot water setpoint** | Setting changes don't show in the report | `sensor: platform: opentherm` `t_dhw_set` |
| Modulation, CH pressure, fault indication | read (card) | optional | [Heating Control Card](card.md) | The card shows less | `rel_mod_level`, `ch_pressure`, `fault_indication` |
| OpenTherm member ID (who made the boiler) | read | optional | **Boiler member ID**: evening report; later a boiler profile you confirm | You pick the boiler by hand when profiles arrive | `sensor: platform: opentherm` `device_id` |
| Maximum capacity and minimum modulation | read | optional | **Boiler maximum capacity**, **Boiler minimum modulation**: [boiler minimum power](experimental.md#low-load-detection) | Minimum power is measured or set by hand | `max_capacity`, `min_mod_level` |

### Never

| Capability | Why |
|---|---|
| A **writable** hot water setpoint (OpenTherm ID 56) | Writing it locks some boilers out: the Atag E325EC stops heating and hot water with C1 51. Set the hot water temperature on the boiler; read it with a sensor. See [Boiler notes](boiler-notes.md). |

## Build your own ESPHome config

For a DIYLess board (or any ESP32 with an OpenTherm adapter) where you keep your own config and add what the integration needs. Every snippet below is an excerpt of [`thermostat.yaml`](../thermostat.yaml), which passes `esphome config` as a whole. Keep the IDs, or change them everywhere they are used.

### 1. OpenTherm hub

```yaml
opentherm:
  in_pin: 21          # DIYLess; your adapter's pins otherwise
  out_pin: 22
  ch_enable: true
  dhw_enable: false   # a combi boiler still makes hot water on demand
  t_room: ch_room_temperature
```

### 2. The winning room's temperature

The PID regulates on this. Point `entity_id` at the integration's **Winning room temperature** sensor. The heartbeat keeps the PID fed when the value doesn't change.

```yaml
sensor:
  - platform: homeassistant
    id: ch_room_temperature
    entity_id: sensor.heating_winning_room_temperature   # yours may differ
    filters:
      - heartbeat: 1s
```

### 3. Flow request with a flow limit

`t_set` on a fixed 0 to 100 °C range; the PID output (0 to 1) times the flow limit is the request. Don't use `auto_max_value` or the boiler's panel maximum as the limit: on some boilers the range then stays 0 to 100 and the boiler follows requests up to its own bound.

```yaml
output:
  - platform: opentherm
    t_set:
      id: t_set
      min_value: 0
      max_value: 100
      zero_means_zero: true
  - platform: template
    id: ch_flow_request
    type: float
    write_action:
      - output.set_level:
          id: t_set
          level: !lambda |-
            float limit = id(max_flow).state;
            if (isnan(limit)) limit = 40;
            return state * limit / 100.0;
      - sensor.template.publish:
          id: flow_request
          state: !lambda |-
            float limit = id(max_flow).state;
            if (isnan(limit)) limit = 40;
            return state * limit;
```

### 4. Flow limit and PID values from Home Assistant

Number entities, restored after a reboot and applied to the PID at boot and on every change. Point **Boiler maximum flow temperature** at `max_flow` and **PID Kp / Ki / Kd** at the three gains.

```yaml
esphome:
  on_boot:
    priority: -100
    then:
      - script.execute: apply_pid_params

script:
  - id: apply_pid_params
    then:
      - climate.pid.set_control_parameters:
          id: main_climate
          kp: !lambda 'return id(main_kp).state;'
          ki: !lambda 'return id(main_ki).state;'
          kd: !lambda 'return id(main_kd).state;'

number:
  - platform: template
    name: "Central heating max flow temperature"
    id: max_flow
    entity_category: config
    unit_of_measurement: "°C"
    device_class: temperature
    optimistic: true
    restore_value: true
    initial_value: 40
    min_value: 25
    max_value: 80
    step: 0.5
  - platform: template
    name: "Central heating Kp"
    id: main_kp
    entity_category: config
    optimistic: true
    restore_value: true
    initial_value: 1.75
    min_value: 0
    max_value: 6
    step: 0.01
    on_value:
      - script.execute: apply_pid_params
  # Central heating Ki (main_ki) and Kd (main_kd) the same way
```

The PID output is a fraction of the limit, so a lower limit heats more gently with the same gains. To keep the response when you change the limit, scale Kp, Ki and Kd by old limit / new limit. Values stored on the device survive a flash: a changed `initial_value` doesn't replace them, so set new values in Home Assistant.

### 5. Requested flow temperature

```yaml
sensor:
  - platform: template
    name: "Central heating requested flow temperature"
    id: flow_request
    unit_of_measurement: "°C"
    device_class: temperature
    state_class: measurement
    accuracy_decimals: 1
    update_interval: never
    filters:
      - or:            # the PID writes every second
          - delta: 0.5
          - heartbeat: 60s
```

### 6. Boiler telemetry

Only add what your boiler reports; not every boiler supports every value.

```yaml
sensor:
  - platform: opentherm
    t_boiler:
      name: "Water temperature"
    t_ret:
      name: "Return water temperature"
    t_dhw_set:
      name: "Domestic hot water temperature setpoint"   # read only
    rel_mod_level:
      name: "Relative modulation level"
    ch_pressure:
      name: "Water pressure in CH circuit"
    device_id:                 # OpenTherm member ID, read once
      name: "Boiler member ID"
      disabled_by_default: false
    max_capacity:
      name: "Boiler maximum capacity"
      disabled_by_default: false
    min_mod_level:
      name: "Boiler minimum modulation"
      disabled_by_default: false

binary_sensor:
  - platform: opentherm
    flame_on:
      name: "Flame on"
    dhw_active:
      name: "Domestic Hot Water active"
    ch_active:
      name: "Central Heating active"
    fault_indication:
      name: "Fault indication"
```

### 7. The PID

```yaml
climate:
  - platform: pid
    id: main_climate
    name: "Central heating"
    heat_output: ch_flow_request
    default_target_temperature: 18
    sensor: ch_room_temperature
    control_parameters:
      kp: 1.75
      ki: 0.0075
      min_integral: 0
```

Pick this climate entity as the **Heat source**. Optional PID sensors (`platform: pid`, types `RESULT`, `ERROR`, `PROPORTIONAL`, `INTEGRAL`, `DERIVATIVE`) show why the loop does what it does; ESPHome reports them x100.

### 8. Fail safe

```yaml
interval:
  - interval: 30s
    then:
      - lambda: |-
          static bool lost = false;
          static uint32_t lost_since = 0;
          if (api::global_api_server->is_connected()) {
            lost = false;
            return;
          }
          if (!lost) {
            lost = true;
            lost_since = millis();
          }
          if (millis() - lost_since >= 5UL * 60UL * 1000UL && !std::isnan(id(ch_room_temperature).state)) {
            ESP_LOGW("failsafe", "No Home Assistant for 5 min: room temperature unknown, heating stops");
            id(ch_room_temperature).publish_state(NAN);
          }
```

Without it the heartbeat keeps feeding the PID the last room temperature, so it keeps heating towards the last target. When Home Assistant connects again the PID resumes.

**Check:** after flashing, the device's logs list every entity at boot, and each entity you point a field at shows up in Home Assistant.

## PID values by thermostat

Which PID decides the flow temperature, and what it starts with, depends on the thermostat. Today the integration runs no PID of its own: it sends the winner's target and, for a firmware PID, the **Winning room temperature**.

| Thermostat | What sets the flow temperature | Starting values | PID advice |
|---|---|---|---|
| ESPHome with `thermostat.yaml` | Firmware PID on the Winning room temperature | Kp 1.75, Ki 0.0075, Kd 0, for a flow limit of 40 °C | Yes, and **Apply PID advice automatically** |
| ESPHome with your own config | Your PID | Your values | Only on the same scale: `climate: platform: pid`, output a fraction of the flow limit, Kp, Ki and Kd as number entities ([section 4](#4-flow-limit-and-pid-values-from-home-assistant)) |
| DIYLess with its stock firmware | Its own PI loop | Kp 30, Ki 0.01 (DIYLess defaults, another scale) | No |
| OpenTherm Gateway with its room thermostat | The room thermostat's own algorithm | Not visible to Home Assistant | No |
| On/off relay | The integration switches the boiler on and off | None | No |

**The starting values are a start, not a tuning.** They come from the reference house (an Atag combi boiler, radiators, a 40 °C limit). The PID output is a fraction of the flow limit, so with another limit the same values heat harder or more gently. To keep the response, scale Kp, Ki and Kd by 40 / your limit ([Hardware](hardware.md#esphome-opentherm-thermostat-thermostatyaml)). From there the [PID advice](experimental.md#warm-up-episodes-and-pid-advice) refines Kp and Ki from your own warm-ups. Kd is never written.

**The PID advice knows one scale.** Its limits (Kp 0.3 to 1.5, Ki 0.0005 to 0.01 on a 0 to 100 °C range) fit an ESPHome PID. Another firmware's values can be 100 times off, and an automatic change on the wrong scale goes straight to your boiler. With anything other than the first two rows, leave **PID Kp / Ki / Kd** empty.

### Where this is going

In v2.2 the PID moves into the integration ([#82](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/82)): every room calculates the flow temperature it needs, and the heat source gets the highest request. The thermostat then only passes a flow setpoint to the boiler, so the PID values, their scale and the learning are the same whatever thermostat you have. Planned to work out of the box with:

- **ESPHome with `thermostat.yaml`:** a flow setpoint mode ([#202](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/202)), with the same 5 minute fail safe as today.
- **DIYLess with its stock firmware:** its manual mode, which takes a target boiler temperature over MQTT ([#203](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/203)).
- **OpenTherm Gateway:** the control setpoint override ([#204](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/204)).

Existing installs keep the firmware PID until you switch.

**When Home Assistant stops: a known limit.** With a flow setpoint, Home Assistant is the controller. `thermostat.yaml` turns the flow off after 5 minutes without Home Assistant. For DIYLess with its stock firmware and for the OpenTherm Gateway, what happens when the setpoints stop coming is up to their firmware, and it isn't documented: they may keep heating at the last flow temperature until Home Assistant is back. That is outside what the integration can control, and accepted. If you want the fail safe, flash ESPHome with `thermostat.yaml`: the board is the same for DIYLess.

## Other thermostats

<!-- Same table as README "Which thermostat": keep both up to date. -->

| Thermostat | Heat source covered | Learning features | In practice |
|---|---|---|---|
| ESPHome with `thermostat.yaml` (DIYLess or any ESP32 OpenTherm adapter) | Full | All | The tested path |
| DIYLess with its stock firmware | Full, with a Home Assistant automation (below) | Gas, night model; no boiler sensors, no PID | Works for heating; no PID advice |
| On/off relay | Full (the integration switches on and off) | Gas, night model; no PID, no flow data | No gentle low flow heating |
| Smart room thermostat with its own sensor | Target only | Gas, night model | A cold bedroom can't start the boiler while the room with the thermostat is warm |
| OpenTherm Gateway with its room thermostat | Target only | Gas, night model, telemetry | Same: the room thermostat decides |

### DIYLess with its stock firmware

What the stock firmware (v2.x, closed source, MQTT with Home Assistant discovery) offers against the table above, from DIYLess's own [configuration overview](https://diyless.com/blog/opentherm-thermostat-cfg-overview) ([#108](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/108)):

- **Entities in Home Assistant:** climate entities only. Discovery creates two devices, *Diyless Thermostat* and *Diyless DHW*, with climates for heating, hot water and manual mode. No sensor entities for flame, flow, return or modulation are documented; the thermostat publishes its state as one JSON message whose fields aren't documented ([#157](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/157)).
- **Regulating on the winning room:** possible. Set its temperature source to *MQTT sensor* and publish the **Winning room temperature** to its `.../properties/temperature` topic from an automation, at least every minute. It is the only way the stock firmware can follow the winning room. It ignores a single change of more than 50 %.
- **Target:** its heating climate entity accepts the target; pick it as the **Heat source**.
- **Fail safe:** built in. Without a valid MQTT temperature for 2 minutes it goes into sensor failure mode and, by default, shuts the boiler down (*Heat on sensor failure* off).
- **Flow limit:** *CH Max* (0 to 80 °C, through the `chmax` MQTT command or its web page). Not an entity the integration can read. DIYLess's own advice matches ours: with another limit in place (a boiler service menu maximum, for example), set CH Max to the same value.
- **PID:** a PI loop with its own gains (Kp default 30, Ki default 0.01) on a different scale than ESPHome's. They can be set through its web page or a JSON `config` message over MQTT, but not as number entities, so there is **no PID advice** and no automatic apply.
- **Boiler identity:** its *Member ID* setting emulates a vendor code for the thermostat itself, to fix compatibility; reading the boiler's own member ID isn't documented.
- **Boiler sensors for the learning features:** not available as entities, as far as the documentation goes. Only the gas meter and outdoor based features work.

**Recommendation:** for anything beyond heating, flash ESPHome. The board is the same; the config above is all it needs.

---

Related: [Learning features](experimental.md), [Heating Control Card](card.md), [`thermostat.yaml`](../thermostat.yaml).
