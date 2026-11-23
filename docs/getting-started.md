# Getting started

From nothing to a heating system with rooms on your dashboard. Every step can be changed later.

## What you need

### Minimum

To get it running at all:

- **Home Assistant 2026.10 or newer.**
- **A heat source Home Assistant can control.** Any of these:
  - an OpenTherm controller you run yourself (see Recommended below);
  - an **on/off relay** on the boiler: full multi-room control, but the boiler only knows on and off, so no gentle low flow heating;
  - a **smart room thermostat** or an **OpenTherm Gateway** with its room thermostat: *target only*. The boiler follows the room where that thermostat hangs, so a cold bedroom can't start it while that room is warm, and the PID advice has nothing to tune. [How it works](how-it-works.md) explains why.
- **A temperature sensor in every room.** Any sensor Home Assistant can see. A room without TRVs still tells the boiler it needs heat.

### Recommended

What this integration is built and tested on, and what the learning features are made for:

- **Thermostat:** a [DIYLess OpenTherm thermostat](https://diyless.com/product/opentherm-thermostat) running ESPHome with [`thermostat.yaml`](hardware.md#esphome-opentherm-thermostat-thermostatyaml). A few euros, two wires to the boiler, no cloud and no account. It replaces the thermostat on your wall and gives full multi-room control. Any OpenTherm adapter with an ESP32 works too, with your own pins in `opentherm:`. Building your own config: [Thermostat requirements](thermostat.md).
- **TRVs**, so a room that doesn't need heat closes while another one heats:
  - [Sonoff TRVZB](https://sonoff.tech/en-nl/products/sonoff-zigbee-thermostatic-radiator-valve): cheaper, fully local over Zigbee (Zigbee2MQTT or ZHA). The first choice where it fits.
  - [Shelly BLU TRV](https://www.shelly.com/products/shelly-blu-trv-single-pack): small, for radiators where space is tight. Bluetooth, through a Shelly BLU gateway.
- **Room sensors:** Xiaomi [LYWSD03MMC](https://www.zigbee2mqtt.io/devices/LYWSD03MMC-z.html), reflashed with Zigbee firmware ([how to flash](https://www.zigbee2mqtt.io/devices/LYWSD03MMC-z.html)). Cheap, tiny, battery powered, on the same Zigbee network as the TRVs, and they report in steps of 0.01 °C, which the [heat-up model](experimental.md#heat-up-model-per-room) needs.
- **Boiler sensors** for the learning features: flame, flow and return temperature and the requested flow come with `thermostat.yaml`; a gas meter (a P1 smart meter reader, for example) for gas per degree-day and costs.

### Optional

- **Radiator booster fans:** DBE boards that blow air across the radiator fins while the radiator still gives off heat, so the same water temperature heats the room faster. Open hardware and ESPHome configs: [BarBaar44/ESPHome/DBE](https://github.com/BarBaar44/ESPHome/tree/main/DBE), board files in [BarBaar44/EasyEDA](https://github.com/BarBaar44/EasyEDA). They work on their own, next to the integration.

[Hardware](hardware.md) has the details and compares the TRVs.

## Install

Search for **Cloudless Multiroom Thermostat** in the Marketplace (Home Assistant 2026.11 and newer) or HACS, install it and restart Home Assistant. Then **Settings > Devices & services > Add integration > Cloudless Multiroom Thermostat**. The dashboard card comes with it.

Not found? The catalog listing is still in review. Use the button, or add the repository by hand as below.

[![Open your Home Assistant instance and open this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BarBaar44&repository=Cloudless-Multiroom-Thermostat&category=integration)
[![Open your Home Assistant instance and start setting up Cloudless Multiroom Thermostat.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cloudless_multiroom_thermostat)

The first button opens the repository in your Home Assistant (the Marketplace on 2026.11 and newer, HACS on 2026.10), ready to install. After installing, the second button starts the setup.

**Home Assistant 2026.11 and newer (Marketplace):**

1. **Settings > Marketplace > Add from link**, enter `BarBaar44/Cloudless-Multiroom-Thermostat` and select **Add**. The Marketplace may ask you to connect GitHub first.
2. Open **Cloudless Multiroom Thermostat**, select **Install** and confirm. Restart Home Assistant if the Marketplace asks for it.
3. **Settings > Devices & services > Add integration > Cloudless Multiroom Thermostat**, if the setup didn't open by itself.

An install from HACS moves to the Marketplace by itself when you update Home Assistant to 2026.11, with the same entities.

**Home Assistant 2026.10 (HACS):**

1. In HACS: **⋮ > Custom repositories**, add `https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat` with type **Integration**.
2. Install **Cloudless Multiroom Thermostat** and restart Home Assistant.
3. **Settings > Devices & services > Add integration > Cloudless Multiroom Thermostat**, or use the second button above.

## The heating system

One heating system has one heat source. Setup asks for the heat source and your first room, nothing more; everything else is a switch on the **Features** page afterwards.

**1. Name and heat source type.**

| Type | Use it for | What it receives |
|---|---|---|
| **On/off switch** | A relay boiler | On when a room is the hysteresis below its target, off when every room reached its target |
| **Climate entity** | An ESPHome or DIYLess OpenTherm thermostat, or any thermostat with a setpoint | The target of the room that needs heat most |
| **OpenTherm Gateway (OTGW)** | The OTGW climate entity | The same target |

The Climate and OTGW types only send a *target*. For real multi-room control the thermostat must also regulate on the winning room's *temperature*, the integration's **Winning room temperature** sensor. The ESPHome PID in [`thermostat.yaml`](hardware.md#esphome-opentherm-thermostat-thermostatyaml) does. A thermostat that regulates on its own sensor heats for the spot where it hangs, whichever room won: see [How it works](how-it-works.md#which-heat-source-gives-full-multi-room-control).

**2. Heat source.**

| Setting | Default | What it does |
|---|---|---|
| Heat source | | The relay, thermostat or OTGW climate entity |
| Central heating enable switch | none | Optional. On while a room that drives the heat source is heating; off while none is (rooms off or paused, or only rooms that heat along) |
| Hysteresis | 0.3 °C | On/off switch only: start when a room is this far below its target, stop when it reaches it |

**3. Your first room,** in three short steps: name and temperatures, the temperature sensor and TRVs, and how it starts (one preset all day, Eco by default, or scheduling off; see [Schedules](schedules.md)). [Rooms](rooms.md) explains every field; for a first room only the name and the temperature sensor matter.

More rooms: **Add room** on the integration page; the gear next to a room edits it.

<p align="center"><img src="https://raw.githubusercontent.com/BarBaar44/Cloudless-Multiroom-Thermostat/main/docs/images/integration-page.png" alt="The integration page: the heating system with its rooms, Add hub and Add room" width="720"></p>

## Features and settings

**Configure** on the heating system opens a menu:

- **System settings:** the heat source entities and these:

  | Setting | Default | What it does |
  |---|---|---|
  | Off temperature | 10 °C | Sent to the heat source and TRVs when nothing should heat (frost protection) |
  | Temperature without schedule | 15 °C | Held by a room without a schedule. See [Schedules](schedules.md) |
  | Skip unchanged TRV writes | on | Saves TRV batteries. When off, the heartbeat also resends every TRV target |
  | Heartbeat | 60 min | How often room temperatures are resent to TRV external inputs, even when unchanged |

- **Features:** one switch per feature, all off on a new system. A feature that is off has no settings page, no entities and no card section; its settings are kept for when you switch it back on.

  | Feature | What it does |
  |---|---|
  | Presence and away | Rooms go off or to eco when everybody leaves. Opens its own page. See [Away](away.md) |
  | Windows | A room pauses while a window in it is open; the window fields appear in the room form. See [Windows](windows.md) |
  | Sun assist | On a sunny morning, rooms that get sun wait for the sun. Opens its own page. See [Sun assist](sun-assist.md) |
  | Guest mode | A *Someone is home* switch that ignores presence. See [Guest mode](away.md#guest-mode) |
  | Learning features | Learn how the house heats. Opens its own page. See [Learning features](experimental.md) |

- A page for each feature that is on and has settings (Presence and away, Sun assist, Learning features).

Upgraded from before the Features page? Features you used stay on: a presence entity set means Presence and away is on, a room with window sensors means Windows is on.

## Check that it works

1. Add the [Heating Control Card](card.md) to a dashboard (reload the browser once after installing).
2. Set a room to **Heat** with a target above its temperature. It shows as the winner, and the heat source gets its target (or switches on, with an on/off switch).
3. Set the target below the temperature. The room shows as reached and the heat source gets the off temperature.

Nothing happens? See [Troubleshooting](troubleshooting.md).

## What next

- **Scheduling** is left to you for now: an automation or a scheduler card that sets presets or temperatures on the room climates. Schedules in the integration are planned for v2.0, see the [roadmap](../ROADMAP.md).
- [Away](away.md) and [Windows](windows.md), if you set a presence entity or window sensors.
- [Learning features](experimental.md), to see how your house heats.
