# Windows

**In one sentence:** while a window or door in a room is open, that room stops heating, and it picks up where it left off when it closes.

## When you want it

In rooms where a window or a garden door is opened for a while, so the radiators don't heat the outside air. It is set per room.

## How to turn it on

Edit the room (the gear next to it on the integration page) and pick its **Window and door sensors** in the second step. Any binary sensor works, as long as `on` means open.

## Settings

| Setting | Default | What it does |
|---|---|---|
| Window and door sensors | none | One or more sensors. The room counts as open while any of them is open |
| Window open delay | 120 s | How long a window must stay open before the room stops heating. Airing for a moment doesn't change anything |
| Window close delay | 60 s | How long all windows must stay closed before the room heats again |

While open, the room is held off: it can't win, and its TRVs get the off temperature. When it closes, the room returns to its own mode and target.

## What you see on the card

The room shows as **Paused** with the reason window. The room gets a **Window** binary sensor that follows the delays, so it shows what the heating acts on, not the raw sensor.

## Common questions

**A window sensor is unavailable. Does the room stop heating?** No. Only `on` counts as open.

**Does a window overrule a manual pause or away?** Yes, a window comes first. When it closes while the room is still paused manually or for away, the room stays paused for that reason.

**My TRV has its own open window detection.** You can leave it on, but it doesn't know about the room sensor or the delays. With window sensors in the integration it isn't needed.
