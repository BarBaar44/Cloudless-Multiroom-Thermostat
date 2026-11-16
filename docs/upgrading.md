# Upgrading

How updates arrive, what to do after one, and what changes between major versions.

## Installing an update

Updates appear under **Settings > Updates** (from the Marketplace on Home Assistant 2026.11 and newer, from HACS on 2026.10). Install it, restart Home Assistant, then reload the browser once so dashboards load the new [Heating Control Card](card.md).

Rooms, settings, presets and targets are kept. So is the data of the [learning features](experimental.md): it lives in files in your own Home Assistant (`config/cloudless_multiroom_thermostat/`), not in the integration.

## Read the release notes

Every release on the [releases page](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/releases) carries its section of the [changelog](../CHANGELOG.md). Look for two things:

- **A change to `thermostat.yaml`.** Some releases need the ESPHome thermostat updated and reflashed (for example the fail safe in v1.5.0). The release notes say so. Copy the changed part into your own config; [Hardware](hardware.md#esphome-opentherm-thermostat-thermostatyaml) explains each block. Values you set in Home Assistant, such as the PID numbers and the flow limit, survive a flash.
- **A behaviour change.** Anything that changes how the house heats is listed first.

## Version numbers

- **Patch (1.8.0 to 1.8.1):** fixes and docs.
- **Minor (1.8 to 1.9):** new features. The release notes say if anything changes for you.
- **Major (1.x to 2.0):** a change in how the integration works. It comes with its own upgrade page here, and the release notes start with what changes for you.

## Coming: v2.0

v2.0 brings schedules in the integration and replaces the 21:00 evening report with live learning data. It is a behaviour change, and it gets its own upgrade guide on this page when it is released. What is planned: the [roadmap](../ROADMAP.md).

**What changes for you when you upgrade** (Home Assistant's log says it too, once per start):

- **Every room needs a schedule.** A room without one holds 15 °C until you make a schedule (one block for the whole day is enough) or turn scheduling off for that room. Automations that set a target on a room without a schedule get a clear error.
- **The evening report goes:** the 21:00 report, the Learning features report sensor, the Evening notification option and the `experimental_report` service. The same information becomes live sensors with long-term statistics, events you can notify from in an automation, and a learning view in the card. If a dashboard or automation uses the report sensor or the service, plan to replace it.
