"""
curve_core - heating curve: the flow limit per outdoor band (#167, observe only)
---------------------------------------------------------------------------------
Plain Python, no Home Assistant. #75 lets the flow limit follow the outdoor
temperature in fixed steps per outdoor band. This learns which values those
steps should have, from what the house does in daily use; no calibration run.

Hold demand: once the room followed is warm, the burner reheats it in short
top-ups. Two top-ups in a row are a hold interval: the burn of the first one
over the time until the second one starts is the duty, the share of time the
house needed the burner to stay on target. A radiator gives off heat roughly
in proportion to how much warmer its water is than the room, so a duty d at
water temperature W means a continuous flow of target + d x (W - target)
would hold the room. That is the hold flow: what the house needs at this
outdoor temperature, whatever the flow limit was when it was measured. Each
hold flow is first predicted from the earlier ones in its band, so the model
proves itself before anything acts on it.

Warm-up reach: warm-ups at the current flow limit show whether the limit is
already used in full (the PID asks for the cap all the time). Then a lower
limit would make warm-ups slower.

The suggested limit per band is the hold flow (upper quartile, so sunny
hours that need less don't pull it down) plus headroom for warm-ups, never
below what warm-ups at the current limit already use in full. Applying it is
#75 (v2.2.0). Nothing here changes the heating or writes the flow limit.
"""

import math
from datetime import datetime

from . import tuner_core

SCHEMA = 1
MIN_GAP_MIN = 10     # minutes between two top-ups; closer is one reheat in two parts
MAX_GAP_MIN = 180    # longer: the room was not simply holding
MIN_N = 5            # hold flows per band before it predicts or suggests
MODEL_N = 9          # prediction: median of this many recent hold flows
SUGGEST_N = 18       # suggestion: upper quartile of this many recent hold flows
HEADROOM = 5.0       # degC above the hold flow, for warm-ups (a first guess)
SATURATED = 0.9      # warm-ups asking this share of the limit on average use it in full
LIMIT_RANGE = (25.0, 80.0)   # the flow limit number in thermostat.yaml
LIMIT_STEP = 0.5


def _minutes(a, b):
    """Minutes from ISO time a to ISO time b."""
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _quartile(values):
    """Upper quartile (nearest rank)."""
    values = sorted(values)
    return values[max(math.ceil(0.75 * len(values)) - 1, 0)]


def _burn_min(episode, hold):
    """Heating burner minutes of a top-up: the episode's flame minutes without hot water, else the hold burn."""
    if episode.get("flame_on_min") is not None:
        return max(episode["flame_on_min"] - (episode.get("dhw_min") or 0), 0)
    return (hold or {}).get("measure", {}).get("burn_min")


def _water(episode, hold):
    """The water temperature the burns reached: at flame off, else the episode peak, else the limit."""
    for value in ((hold or {}).get("measure", {}).get("water_at_off"), episode.get("water_peak"), episode.get("max_ch")):
        if value is not None:
            return value
    return None


def interval(first, second, hold=None):
    """
    The hold interval from top-up `first` to the next episode of the same
    room, `second`. hold is first's hold record (#163), if any.
    Returns {gap_min, burn_min, duty, water, hold_flow} or {"reason": ...}.
    """
    if tuner_core.episode_kind(second) != "top_up":
        return {"reason": "not_holding"}
    if first.get("target") is None or first.get("target") != second.get("target"):
        return {"reason": "target_changed"}
    if first.get("low_load"):
        # The boiler can't burn below its minimum: the duty overstates the need
        return {"reason": "low_load"}
    if (hold or {}).get("measure", {}).get("reason") == "hot_water":
        return {"reason": "hot_water"}
    gap = _minutes(first["start"], second["start"])
    if not MIN_GAP_MIN <= gap <= MAX_GAP_MIN:
        return {"reason": "gap"}
    burn = _burn_min(first, hold)
    water = _water(first, hold)
    if not burn or water is None:
        return {"reason": "no_data"}
    target = first["target"]
    duty = min(burn / gap, 1.0)
    return {
        "gap_min": round(gap),
        "burn_min": burn,
        "duty": round(duty, 2),
        "water": water,
        "hold_flow": round(target + duty * max(water - target, 0.0), 1),
    }


def model(records, room_id, band):
    """
    The predicted hold flow for this room and band: the median of the last
    MODEL_N after MIN_N. Returns {hold_flow, n} or None.
    """
    rows = [r for r in records if r.get("room_id") == room_id and r.get("band") == band and "hold_flow" in r]
    rows = rows[-MODEL_N:]
    if len(rows) < MIN_N:
        return None
    return {"hold_flow": round(_median([r["hold_flow"] for r in rows]), 1), "n": len(rows)}


def record(first, second, hold, records):
    """
    The curve record for one hold interval: predicted from the earlier
    records of the room and band, then measured.
    """
    band = tuner_core.outdoor_band(first.get("outdoor_avg"))
    rec = {"schema": SCHEMA, "start": first["start"], "room_id": first.get("room_id"), "band": band,
           "max_ch": first.get("max_ch"), "target": first.get("target")}
    m = interval(first, second, hold)
    if "reason" in m:
        return {**rec, "reason": m["reason"]}
    pred = model(records, rec["room_id"], band)
    if pred:
        pred = {**pred, "error": round(pred["hold_flow"] - m["hold_flow"], 1)}
    return {**rec, **m, "prediction": pred}


def pairs(episodes):
    """
    (first, second) for every top-up and the next episode of the same room,
    in start order. The last episode of a room has no pair yet.
    """
    last = {}
    out = []
    for ep in sorted(episodes, key=lambda e: e["start"]):
        room_id = ep.get("room_id")
        if room_id is None:
            continue
        before = last.get(room_id)
        if before is not None and tuner_core.episode_kind(before) == "top_up":
            out.append((before, ep))
        last[room_id] = ep
    return out


def _round_limit(value):
    """Up to the flow limit number's step, inside its range."""
    value = math.ceil(value / LIMIT_STEP) * LIMIT_STEP
    return min(max(value, LIMIT_RANGE[0]), LIMIT_RANGE[1])


def warm_ups(episodes, room_id):
    """Valid warm-ups of the room at the latest flow limit and schema, with a requested flow."""
    ups = [e for e in episodes
           if e.get("room_id") == room_id and e.get("valid") and tuner_core.episode_kind(e) == "warm_up"
           and e.get("max_ch") and e.get("flow_req_avg") is not None]
    if not ups:
        return []
    last = ups[-1]
    return [e for e in ups if e["max_ch"] == last["max_ch"]
            and tuner_core.schema_of(e) == tuner_core.schema_of(last)]


def summary(records, episodes, room_id, name):
    """
    Per outdoor band for the room followed: the hold flows, the prediction
    errors, the warm-ups at the current limit and the suggested limit.
    Returns {room_id, room, limit, holds, bands: {band: {...}}} or None.
    """
    holds = [r for r in records if r.get("room_id") == room_id and "hold_flow" in r]
    ups = warm_ups(episodes, room_id)
    if not holds and not ups:
        return None
    limit = ups[-1]["max_ch"] if ups else next((r["max_ch"] for r in reversed(holds) if r.get("max_ch")), None)
    bands = {}
    for band in tuner_core.BAND_NAMES:
        rows = [r for r in holds if r["band"] == band]
        band_ups = [e for e in ups if tuner_core.outdoor_band(e.get("outdoor_avg")) == band]
        if not rows and not band_ups:
            continue
        v = {"holds": len(rows), "warm_ups": len(band_ups), "hold_flow": None, "errors": [],
             "use": None, "suggested": None, "why": None}
        if rows:
            v["hold_flow"] = round(_median([r["hold_flow"] for r in rows[-MODEL_N:]]), 1)
            v["errors"] = [r["prediction"]["error"] for r in rows if (r.get("prediction") or {}).get("error") is not None][-MODEL_N:]
        if band_ups:
            v["use"] = round(_median([e["flow_req_avg"] / e["max_ch"] for e in band_ups]), 2)
        if len(rows) >= MIN_N:
            suggested = _round_limit(_quartile([r["hold_flow"] for r in rows[-SUGGEST_N:]]) + HEADROOM)
            if limit is not None and v["use"] is not None and v["use"] >= SATURATED and suggested < limit:
                v["suggested"], v["why"] = limit, "warm_ups_use_the_limit"
            else:
                v["suggested"] = suggested
                v["why"] = "hold_flow" if v["use"] is not None else "no_warm_ups"
        bands[band] = v
    return {"room_id": room_id, "room": name, "limit": limit, "holds": len(holds), "bands": bands}


def summary_line(s):
    """Evening report line: hold flow and suggested limit per outdoor band."""
    if not s or not s["bands"]:
        return None
    bits = []
    for band, v in s["bands"].items():
        parts = []
        if v["hold_flow"] is not None:
            text = f"holds at {v['hold_flow']:g} °C ({v['holds']})"
            if v["errors"]:
                text += f", predicted within {sum(abs(e) for e in v['errors']) / len(v['errors']):.1f}"
            parts.append(text)
        if v["use"] is not None:
            parts.append(f"warm-ups ask {round(v['use'] * 100)}% of the limit ({v['warm_ups']})")
        if v["suggested"] is not None:
            parts.append(f"suggested limit {v['suggested']:g} °C")
        bits.append(f"{tuner_core.BAND_NAMES[band]} °C: {', '.join(parts)}")
    limit = f", now {s['limit']:g} °C" if s["limit"] is not None else ""
    return f"- Heating curve (learned, never applied): {s['room']}{limit}. Outdoor " + "; ".join(bits)
