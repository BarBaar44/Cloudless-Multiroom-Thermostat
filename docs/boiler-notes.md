# Boiler notes

Issues found with one boiler brand or model. They are not caused by the integration, but by what an OpenTherm thermostat sends to that boiler.

## Atag E325EC: set the hot water temperature on the boiler, never from the thermostat (C1 51)

Found on an **Atag E325EC** combi boiler (2015). Other Atag models may do the same, but that has not been tested.

> **Set the hot water temperature on the boiler's own panel.** When the thermostat sends a new hot water temperature to this boiler, the boiler stops working: no heating and no hot water, until the thermostat stops sending it. Showing the hot water temperature in Home Assistant is fine; changing it from there is not.

**What you see:** the boiler stops heating and gives no hot water. Its display shows an error that looks like a broken fan, and a reset only helps for a few seconds. The fan is fine: with the thermostat disconnected the boiler works normally again.

**After a reset or a power cut** the boiler first runs its air removal program for about 7 minutes. The display shows a code during that time; that is normal, wait until it is done.

**If the boiler stops like this:**

1. Disconnect the thermostat, reset the boiler and open a hot water tap. If you get hot water, the boiler is fine and something the thermostat sends is the cause.
2. Remove what the thermostat writes to the boiler, the most recently added first, and the hot water temperature in any case.
3. Only if the error also comes back with nothing connected is it the fan, its wiring or the control board: a job for your installer.

**Technical details**, for looking things up:

- The display shows **C1 51**, which Atag fault lists describe as a fan fault. In Home Assistant "Fault indication" turns on and the flame stays off on every demand.
- The trigger is a write of the hot water setpoint, **OpenTherm data ID 56**. Reading ID 56 is fine. Confirmed in this house, also through an OpenTherm Gateway.
- The air removal program shows as **C1 05** (or C0 05); the fault bit can stay on until it finishes.
- The ESPHome log shows every message the thermostat sends (`WRITE_DATA; id: ...`); with `web_server:` enabled you can follow it at `http://<thermostat-ip>/events`.

## Your boiler isn't listed

Most boilers simply work. If yours does something odd that goes away with the thermostat disconnected, please [open an issue](https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat/issues) with the make, the model and what the display shows, so it can be added here.
