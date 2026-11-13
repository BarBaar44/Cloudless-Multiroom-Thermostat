# Hardware

What the integration talks to, and the hardware it was built and tested on. Any TRV and temperature sensor Home Assistant can see will do; the choice that matters most is the heat source.

## Heat sources

| Heat source | Type in the setup | Multi-room | Notes |
|---|---|---|---|
| OpenTherm controller you run yourself: a [DIYLess OpenTherm thermostat](https://diyless.com/product/opentherm-thermostat) or any OpenTherm adapter with an ESP32, with [`thermostat.yaml`](#esphome-opentherm-thermostat-thermostatyaml) | Climate entity | Full | Recommended. Modulates the flow temperature for the winning room; what the learning features and the PID advice are made for |
| On/off relay | On/off switch | Full | The boiler only knows on and off, so no gentle low flow heating |
| Smart room thermostat with its own sensor | Climate entity | Target only | The boiler follows the room where the thermostat hangs |
| OpenTherm Gateway (OTGW) with its room thermostat | OpenTherm Gateway | Target only | Same: the room thermostat decides |

*Target only* means the integration still runs every room's TRVs, but a cold bedroom can't start the boiler while the room with the thermostat is warm. [How it works](how-it-works.md#which-heat-source-gives-full-multi-room-control) explains why. The recommended path from an OTGW or a smart thermostat is to replace the room thermostat with an OpenTherm controller and let the virtual thermostats take over.

**DIYLess boards with their own firmware** (instead of ESPHome): whether they can regulate on the **Winning room temperature** and which features match `thermostat.yaml` is being checked for v1.9 ([#108](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues/108)). Until then, ESPHome with `thermostat.yaml` is the tested path.

## ESPHome OpenTherm thermostat (`thermostat.yaml`)

[`thermostat.yaml`](../thermostat.yaml) is the ESPHome config for the DIYLess OpenTherm thermostat, from `opentherm:` on. Use it with the **Climate entity** heat source: the integration sets the PID climate's target to the winner's target, and the firmware reads the winner's temperature as its process value.

- **`opentherm:`** OpenTherm master on GPIO 21 (in) and 22 (out), central heating enabled. The hot water enable flag is sent as off; this combi boiler still makes hot water on demand, at the setpoint set on its own panel.
- **`output:`** `t_set` is the boiler's target flow temperature on a fixed 0 to 100 °C range (`zero_means_zero`, so 0 means boiler off). The PID drives `ch_flow_request`, which writes its output times the flow limit to `t_set`. The limit is the **Central heating max flow temperature** number (default 40 °C), set from Home Assistant without reflashing. Don't rely on the boiler's panel maximum or `auto_max_value` instead: on the ATAG here `auto_max_value` left the range at 0 to 100, and the boiler followed requests up to its own bound of 50 °C with its panel maximum at 40. Point the learning features' **Boiler maximum flow temperature** field at this number.
- **`climate: platform: pid`** (`main_climate`, "Central heating") the control loop. Its room temperature comes from Home Assistant: point it at the integration's **Winning room temperature** sensor (the example uses `sensor.virtual_heating_temperature`; rename the sensor to that, or change the ID). A 1 second heartbeat filter keeps the PID fed when the value doesn't change. Starting values `kp: 1.75`, `ki: 0.0075`, for a flow limit of 40. The PID output is a fraction of the limit, so changing the limit changes how hard the same Kp and Ki heat: a lower limit heats more gently. To keep the response when you change the limit, scale Kp, Ki and Kd by old limit / new limit (40 to 50: 1.4 and 0.006).
- **`interval:` fail safe** after 5 minutes without a Home Assistant connection the room temperature is set to unknown, and the PID turns its output off (it does that when its sensor is NaN). Without it the heartbeat would keep feeding the PID the last value, so it would keep heating towards the last target. When Home Assistant connects again it sends the current value and the PID resumes. If your config already has an `interval:` block, add this entry to it.
- **`sensor`, `binary_sensor`, `switch`** the OpenTherm telemetry this boiler supports: modulation, pressure, flow, return and hot water temperatures, faults, flame, pump, and the central heating, hot water and outside temperature compensation switches.

**Runtime-adjustable PID values.** "Central heating Kp / Ki / Kd" are number entities that apply to `main_climate` on every change and at boot, so values set in Home Assistant survive a reboot. A changed starting value in the YAML doesn't replace a stored value, so after a flash set new values in Home Assistant. Coming from the 0 to 100 range (`auto_max_value`) with a limit of 40: multiply Kp, Ki and Kd by 2.5. "Central heating PID Result / Error / Proportional / Integral / Derivative" sensors show why the loop does what it does (ESPHome reports them x100). `min_integral: 0`: the loop only heats, so a negative integral is never useful and would otherwise have to unwind every morning. The [PID advice](experimental.md#warm-up-episodes-and-pid-advice) works with these numbers.

See [Boiler notes](boiler-notes.md) before adding writes for your boiler.

## The setup this was built on

The hardware this was built and tested on. None of it is required: any TRV and temperature sensor Home Assistant can see will do.

| Component | Choice | Why |
|---|---|---|
| Boiler | Atag E325ec (2015) | Supports OpenTherm out of the box |
| Thermostat | [DIYLess OpenTherm thermostat](https://diyless.com/product/opentherm-thermostat) with custom ESPHome ([`thermostat.yaml`](../thermostat.yaml)) | Full local control over the PID loop and the OpenTherm bus |
| TRVs | [Sonoff TRVZB](https://sonoff.tech/en-nl/products/sonoff-zigbee-thermostatic-radiator-valve) and [Shelly BLU TRV](https://www.shelly.com/products/shelly-blu-trv-single-pack) | Sonoff where it fits; Shelly where space is tight |
| Room sensors | Xiaomi/Aqara [LYWSD03MMC](https://www.zigbee2mqtt.io/devices/LYWSD03MMC-z.html), reflashed with Zigbee firmware | Cheap, tiny, battery powered, on the same local Zigbee mesh as the TRVs |
| Radiator booster fans | Custom "DBE" ESPHome boards ([BarBaar44/ESPHome/DBE](https://github.com/BarBaar44/ESPHome/tree/main/DBE)) | Push air through the radiator fins to get more heat out of the same water temperature |

**TRVs compared:**

| | Sonoff TRVZB | Shelly BLU TRV |
|---|---|---|
| Size | Bulkier | Small, about the size of a Tado TRV |
| Cost | Cheaper | More expensive |
| Connectivity | Fully local via Zigbee2MQTT | Bluetooth, needs a BLU gateway |
| External temperature input | Yes | Yes |

Sonoff is the better choice where it fits: cheaper, fully local and well supported.

**Room sensors:** the LYWSD03MMC speaks Bluetooth with its stock firmware. Reflashed with Zigbee firmware ([instructions on the Zigbee2MQTT page](https://www.zigbee2mqtt.io/devices/LYWSD03MMC-z.html)) it joins the same Zigbee network as the TRVs, so no Bluetooth proxies are needed per room.

**Booster fans:** each radiator has a fan board that measures flow and return temperature and blows air across the fins while the radiator still gives off heat. They work independently of the integration: they make the heat a radiator receives reach the room faster, whichever room is the winner. Hardware files are in [BarBaar44/EasyEDA](https://github.com/BarBaar44/EasyEDA).
