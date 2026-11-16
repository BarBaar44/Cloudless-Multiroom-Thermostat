# Troubleshooting

Common problems, roughly in the order people run into them. Not listed? See [Finding the cause](#finding-the-cause) and [open an issue](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues).

## The card

**"Custom element doesn't exist: heating-control-card".** Reload the browser once after installing or updating. On a dashboard in YAML mode, add the resource yourself: [Heating Control Card](card.md#how-it-gets-on-your-dashboard).

**The log warns about two copies of the card.** The separately installed Heating Control Card is still there. Remove it in HACS or the Marketplace and its entry under **Settings > Dashboards > ⋮ > Resources**.

**"Thermostat offline" in the header.** The boiler or flame entity of the card is unavailable. Check the thermostat in ESPHome, or point the card's boiler options at your own entities: [card settings](card.md#settings).

## Rooms

**A room is below target but the boiler doesn't run.** Look at the room's `role` on the card or in its attributes:

- `paused`: a window, a manual pause or away holds it off. `paused_reason` says which.
- `waiting`: **Drives the heat source** is off for this room. It only heats along when another room drives the heat source. See [Rooms](rooms.md#drives-the-heat-source).
- `calls_for_heat` with an on/off switch: the room is less than the hysteresis (0.3 °C by default) below its target.
- `winner`, but the boiler still doesn't heat: the heat source gets the target but decides itself. With a thermostat that regulates on its own sensor or an OpenTherm Gateway, the spot where that thermostat hangs is warm enough. See [How it works](how-it-works.md#which-heat-source-gives-full-multi-room-control).

**Rooms stay paused for away while someone is home.** Check the presence entity: `home`, `on` or a `zone.home` count above 0 means home. A person in another zone counts as away. See [Away](away.md).

**A room reaches its target, but the TRV keeps the radiator cold or hot.** The TRV regulates on its own sensor on the radiator. Add its **TRV external temperature input** to the room, so it gets the room temperature: [Rooms](rooms.md#trv-external-temperature-inputs).

**A TRV was switched off.** On the device or by another automation: a TRV that is off ignores every setpoint. The integration puts it back to heat by itself. If something keeps switching it off, find that automation.

**The winner's TRV shows a target 1 °C higher than the room.** That is the overshoot buffer, on purpose: [The overshoot buffer](how-it-works.md#the-overshoot-buffer).

## The boiler

**The boiler keeps heating while every room is warm, or stops while a room is cold.** The heat source regulates on its own sensor instead of the **Winning room temperature**. With `thermostat.yaml`, check that the PID's sensor points at the integration's Winning room temperature sensor: [Hardware](hardware.md#esphome-opentherm-thermostat-thermostatyaml).

**The boiler stops with a fault and comes back when the thermostat is disconnected.** Something the thermostat sends upsets the boiler. See [Boiler notes](boiler-notes.md).

## Learning features

**A feature shows nothing.** Each feature starts once the entities it needs are set: [Which fields each feature needs](experimental.md#which-fields-each-feature-needs). Gas per degree-day also needs long-term statistics on the gas meter and the outdoor temperature.

**No night prediction, and the log says "No hourly forecast from …".** The weather entity has no hourly forecast. Pick one that has: [Weather forecast](experimental.md#weather-forecast).

## Finding the cause

1. **Look at the attributes.** The room climate's `role`, `paused_reason` and `effective_target`, and the Winning room sensor's attributes, show what the integration decided and why. [Reference](reference.md) lists them all.
2. **Turn on debug logging.** On the integration page, **⋮ > Enable debug logging**, reproduce the problem, then **Disable debug logging** to download the log. Or in `configuration.yaml`:

   ```yaml
   logger:
     logs:
       custom_components.cloudless_multiroom_thermostat: debug
   ```

3. **Try it in the simulated house.** [`dev/`](../dev/README.md) runs the integration against a simulated house, without touching your heating.

When you open an issue, add the version, the heat source type, what you expected, what happened, and the debug log.
