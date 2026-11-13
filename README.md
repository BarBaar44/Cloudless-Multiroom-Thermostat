

<p align="center">
  <a href="https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/releases"><img src="https://img.shields.io/github/v/release/BarBaar44/Cloudless-Multiroom-Thermostat?style=for-the-badge&label=release" alt="Release"></a>
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-custom-orange?style=for-the-badge" alt="HACS custom"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.10%2B-41BDF5?style=for-the-badge" alt="Home Assistant 2026.10+">
  <a href="https://community.home-assistant.io/t/cloudless-multiroom-thermostat/1032363"><img src="https://img.shields.io/badge/community-forum-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Community forum thread"></a>
</p>

<p align="center"><img src="https://raw.githubusercontent.com/BarBaar44/Cloudless-Multiroom-Thermostat/main/custom_components/cloudless_multiroom_thermostat/brand/icon@2x.png" alt="Cloudless Multiroom Thermostat logo" width="160"></p>

# Cloudless Multiroom Thermostat

A Home Assistant integration for multi-room central heating without a cloud. Any number of rooms, each with its own temperature sensor and radiator valves, share one heat source: the room that needs heat most drives the boiler, and every other room heats along through its own valves. Everything is set up from the UI and runs locally.

Other integrations put a smart controller on the boiler. This one puts a [virtual thermostat in every room](docs/how-it-works.md) and lets the boiler serve them. The one requirement is an OpenTherm controller you run yourself, such as a DIYLess or a generic OpenTherm module with an ESP32: a few euros, two wires to the boiler, and ESPHome. In return each room gets its own control, the integration learns from how your house actually heats instead of a calibration run, and it is built for houses that heat several rooms independently.

- **No cloud:** Home Assistant, your TRVs and your boiler thermostat, nothing else.
- **Any number of rooms**, each with its own target, presets and window sensors.
- **One heat source**, as an on/off relay, an OpenTherm thermostat (ESPHome, DIYLess) or an OpenTherm Gateway. Full multi-room control needs a relay or an OpenTherm controller without its own room sensor, see [Hardware](docs/hardware.md).
- **Presence aware:** rooms go off or to eco when everybody is away, and come back when someone is home.
- **Open window detection** per room.
- **Its own dashboard card**, included.

<p align="center"><img src="https://raw.githubusercontent.com/BarBaar44/Cloudless-Multiroom-Thermostat/main/docs/images/card.png" alt="Heating Control Card" width="412"> <img src="https://raw.githubusercontent.com/BarBaar44/Cloudless-Multiroom-Thermostat/main/docs/images/card-multi-room.png" alt="Heating Control Card with several rooms" width="412"></p>

The **Heating Control Card** shows every room with its temperature, target, Heat/Off and role, highlights the room the boiler heats for, and shows the boiler state: heating, pumping or hot water, modulation, faults and pressure warnings. It comes with the integration, no separate install: [docs/card.md](docs/card.md).

## Running in 10 minutes

You need Home Assistant 2026.10 or newer, a temperature sensor in every room and a heat source Home Assistant can control. TRVs are optional. [What you need](docs/getting-started.md#what-you-need) explains the choices.

1. **Install.** Search for **Cloudless Multiroom Thermostat** in the Marketplace (Home Assistant 2026.11 and newer) or HACS, install it and restart Home Assistant. Not found? The catalog listing is still in review: use the button below, or [add the repository by hand](docs/getting-started.md#install).

   [![Open your Home Assistant instance and open this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BarBaar44&repository=Cloudless-Multiroom-Thermostat&category=integration)

2. **Add the heating system.** **Settings > Devices & services > Add integration > Cloudless Multiroom Thermostat**, or this button. Pick the heat source type and its entity; the other settings can keep their defaults.

   [![Open your Home Assistant instance and start setting up Cloudless Multiroom Thermostat.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cloudless_multiroom_thermostat)

3. **Add your rooms.** On the integration page, **Add room** for every room: a name and temperatures, then its temperature sensor and TRVs.
4. **Add the card.** Reload the browser once, then add a card of type `custom:heating-control-card` to a dashboard. It finds the rooms by itself.

Set a room to Heat and give it a target above its temperature: it becomes the winner and the heat source gets its target. [Getting started](docs/getting-started.md) walks through every step and what to check.

## Documentation

| Page | What it covers |
|---|---|
| [Getting started](docs/getting-started.md) | What you need, install, the heating system settings, your first room |
| [How it works](docs/how-it-works.md) | A virtual thermostat in every room, the winner and the two tiers |
| [Rooms](docs/rooms.md) | Room settings, presets, rooms that only heat along, roles |
| [Away](docs/away.md) | What happens when everybody leaves |
| [Windows](docs/windows.md) | Open window detection per room |
| [Heating Control Card](docs/card.md) | The dashboard card and its options |
| [Learning features](docs/experimental.md) | Optional features that learn how your house heats |
| [Hardware](docs/hardware.md) | Heat sources, DIYLess, `thermostat.yaml`, TRVs and sensors |
| [Boiler notes](docs/boiler-notes.md) | Known problems with specific boilers |
| [Upgrading](docs/upgrading.md) | Updates, release notes, what to do after one |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and how to find the cause |
| [Reference](docs/reference.md) | Every entity, attribute and service |

[CHANGELOG.md](CHANGELOG.md) lists what changed per release; [ROADMAP.md](ROADMAP.md) where it is going.

## Why this exists

I have been using Home Assistant for several years. One of the main reasons is automating my house with little or no cloud dependency. Over the years, some cloud dependencies still crept in quietly: Home Connect, SmartThings and Tado. Then Tado, and later SmartThings, announced changes to their business model that make users pay for connectivity.

When Tado did, more than a year ago, I started building a local heating system I had full control over. The hardware turned out to be the easy part. On the Home Assistant forum I found [a post by Dujith](https://community.home-assistant.io/t/opentherm-multi-room-brainstorming-ideas/337784) with a Home Assistant template holding a basic version of what is now one of the core principles: the two tier system. Kudos to him! I extended the template, added automations and ended up with a pretty good basic system, which heated my house for a full season before it became this integration. Having full control gave me insights and ideas, and opened the door to a much more efficient heating system.

Things really took off when I started using Claude Code for the programming, a skill I lack. That is how development works today: I design, review, monitor and make sure we are heading in the right direction. Claude Code writes the code.

Where it is going next: [ROADMAP.md](ROADMAP.md).

## Development

- [`dev/`](dev/README.md): a simulated house (rooms that warm up and cool down, TRVs, a thermostat with a PID like `thermostat.yaml`, a boiler that short cycles like a real one, gas meter and weather) to try everything without hardware, as a Docker container or a VM for Virtual Machine Manager, with a script that sets it all up through the real forms.
- `tests/`: tests on a real Home Assistant core (`pip install -r requirements_test.txt`, then `pytest`). CI also runs ruff, shellcheck, hassfest and the HACS validation.
- Every pull request that changes what users see or do also changes its page in [`docs/`](docs/).
