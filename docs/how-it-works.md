# How it works

The ideas behind the integration. You don't need them to set it up, but they explain what you see on the card.

## A virtual thermostat in every room

A traditional setup has one physical thermostat in one room. Its built-in sensor decides when the boiler runs, so the whole house heats to what that one spot measures.

This integration turns that around. Every room gets its own **virtual thermostat** (a climate entity with its own sensor and target), and the boiler is driven by a controller that has **no room sensor of its own**: it heats for whichever room needs it most, using that room's temperature. There is no physical room thermostat in charge anymore.

That is the way forward, and it decides which heat source gives you real multi-room control.

## Which heat source gives full multi-room control

| Heat source | Who decides when the boiler runs | Multi-room |
|---|---|---|
| **On/off switch** (relay) | The integration, from the room temperatures | Full |
| **Climate entity** with an ESPHome or DIYLess PID fed the [Winning room temperature](reference.md#system-entities) (like [`thermostat.yaml`](hardware.md#esphome-opentherm-thermostat-thermostatyaml)) | The controller, on the winning room's temperature | Full |
| **Climate entity** of a thermostat with its own built-in sensor | That thermostat, on the temperature where it hangs | Target only |
| **OpenTherm Gateway** with a room thermostat connected | That room thermostat, on its own sensor | Target only |

With *target only*, the integration still runs every room's TRVs, but boiler demand follows the room where the physical thermostat hangs. If you have an OTGW or a smart room thermostat now, the recommended path is to replace the room thermostat with an OpenTherm controller (such as a DIYLess board running [`thermostat.yaml`](hardware.md#esphome-opentherm-thermostat-thermostatyaml)) and let the virtual thermostats take over.

## Two tiers

A boiler has only **one** flow temperature, while every room wants its own. Two tiers solve that without any room coordination:

**Tier 1, the heat source:** of all rooms set to heat, the one with the biggest gap between target and temperature is the **winner**. Its target goes to the heat source; with an ESPHome PID thermostat the boiler then modulates its flow temperature to bring exactly that room to its target. When no room has a real gap, the heat source gets the off temperature.

**Tier 2, the valves:** every room's TRVs get the room's target and regulate their own valve. Home Assistant never commands valve positions: as long as the water arriving is warm enough for a room's own target, its TRVs stay open and the room heats along (a **passenger**). When a room reaches its target, its TRVs close by themselves. Rooms are held off with the off temperature, never with the TRV's own off mode: a TRV that is switched off (on the device or by another automation) ignores every setpoint, so it is put back to heat. Only a room that wants more than the current winner waits, until it becomes the winner itself, which happens as soon as its gap is the largest.

## The overshoot buffer

The winning room's TRVs get their target plus the buffer (default 1 °C); passengers get their exact target. Two controllers watch the winning room at once: the boiler's PID, which eases off its modulation gradually, and that room's TRV. Without headroom the TRV starts closing while the boiler is still pushing hot water, a fight that wastes heat and can trip a low-flow fault. A passenger's TRV can't get into that fight, because the boiler isn't modulating for it. The buffer moves with the winner.

## Rooms that only heat along

Turn off **Drives the heat source** for a room that may be heated but must never make the heat source run, such as a hallway that cools much faster than the rest of the house and would otherwise keep winning. Such a room never becomes the winner, never starts an on/off heat source and doesn't turn on the central heating enable switch. Its TRVs still get its target, so it heats along as a passenger whenever another room drives the heat source. While nothing else needs heat, its role is `waiting`. Set it on the room: [Rooms](rooms.md#drives-the-heat-source).

## One temperature per room

The room sensor's reading is also pushed to the TRVs' external temperature inputs, with a heartbeat (some TRVs, like the Sonoff TRVZB, fall back to their own sensor after 2 hours without an update). A TRV's own sensor sits on the radiator and reads warm; this way the room climate, the winner choice and the TRV all work from the same number. TRV writes are skipped when nothing changed, to save batteries.

## Windows and presence

An open window (after its open delay) holds its room off and sets its TRVs to the off temperature; when it closes, the room returns to its own mode and target. When everybody is away, rooms go off or to eco; they return when someone is home. Window has priority over a manual pause, which has priority over away. Details: [Windows](windows.md) and [Away](away.md).
