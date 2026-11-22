"""
hold_core - the hold profile: coast after daytime reheats (#163, observe only)
-------------------------------------------------------------------------------
Plain Python, no Home Assistant. Once a room is warm, the burner reheats it
in short top-ups. The flame stops when the room is back at target, but the
water in the radiators still carries heat: the room keeps rising after the
burner is off. That rise is the coast, and it is most of a top-up's
overshoot: it happens after the burner stopped, so PID gains can't reach it.

Each top-up with kept minute samples gets a record: the coast, the room
against target when the flame stopped, the dip before the reheat, the burn,
the flow, and the hour. The coast is modelled per room, time of day block and
outdoor band, and every top-up is first predicted from the earlier ones, so
the model has to prove itself before anything acts on it (#164: stopping
early by the predicted coast, after v2.0). Nothing here changes the heating.
"""

from . import tuner_core

SCHEMA = 1
MIN_AFTER_MIN = 10   # minutes of samples after the flame stops, to see the coast
MIN_N = 5            # coasts per cell before it predicts
MODEL_N = 9          # median over this many recent coasts
DHW_MAX_MIN = 2      # more hot-water minutes than this in the burn: the radiators got less heat

# Time of day blocks, by the hour the flame stopped (local time). The coast
# grows through the day (more stored heat in the house, sun, cooking).
BLOCKS = (("0_10", 0, 10), ("10_13", 10, 13), ("13_15", 13, 15), ("15_24", 15, 24))
BLOCK_NAMES = {"0_10": "before 10:00", "10_13": "10:00 to 13:00", "13_15": "13:00 to 15:00", "15_24": "after 15:00"}


def block_of(hour):
    """The time of day block for an hour (0 to 23)."""
    for name, start, end in BLOCKS:
        if start <= hour < end:
            return name
    return None


def _hour(sample):
    """Local hour from a sample's ISO time (the offset is kept, so [11:13] is local)."""
    try:
        return int(sample["t"][11:13])
    except (KeyError, TypeError, ValueError):
        return None


def measure(samples):
    """
    The coast of one top-up from its minute samples.
    Returns {coast, at_off, dip, burn_min, flow_req_max, water_at_off, hour}
    or {"reason": ...}.
    """
    if not samples or samples[0].get("target") is None:
        return {"reason": "no_data"}
    target = samples[0]["target"]
    # A target change or an open window ends what can be judged; the coast
    # before it still counts when enough of it was seen
    end = next((i for i, s in enumerate(samples) if s.get("target") != target or s.get("garden_paused")), len(samples))
    samples = samples[:end]
    on = next((i for i, s in enumerate(samples) if s.get("flame")), None)
    if on is None:
        return {"reason": "no_burn"}
    off = next((i for i in range(on + 1, len(samples)) if not samples[i].get("flame")), None)
    if off is None:
        return {"reason": "burn_not_ended"}
    after = samples[off:]
    if len(after) < MIN_AFTER_MIN:
        return {"reason": "too_short"}
    if len([1 for s in samples[on:off] if s.get("dhw")]) > DHW_MAX_MIN:
        return {"reason": "hot_water"}
    room_off = samples[off].get("room")
    rooms_after = [s["room"] for s in after if s.get("room") is not None]
    rooms_before = [s["room"] for s in samples[: off + 1] if s.get("room") is not None]
    if room_off is None or not rooms_after or not rooms_before:
        return {"reason": "no_data"}
    hour = _hour(samples[off])
    flow_req = [s["flow_req"] for s in samples[on:off] if s.get("flow_req") is not None]
    return {
        "coast": round(max(rooms_after) - room_off, 2),
        "at_off": round(room_off - target, 2),
        "dip": round(max(target - min(rooms_before), 0.0), 2),
        "burn_min": off - on,
        "flow_req_max": max(flow_req) if flow_req else None,
        "water_at_off": samples[off].get("water"),
        "hour": hour,
        "block": block_of(hour) if hour is not None else None,
    }


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def model(records, room_id, block, band):
    """
    The predicted coast for this room, block and band: the median of the last
    MODEL_N coasts in that cell after MIN_N, else of the block over all bands
    (the cell is still filling). Returns {coast, n, source} or None.
    """
    mine = [r for r in records
            if r.get("room_id") == room_id and r.get("block") == block and "coast" in (r.get("measure") or {})]
    for source, rows in (("cell", [r for r in mine if r.get("band") == band]), ("block", mine)):
        rows = rows[-MODEL_N:]
        if len(rows) >= MIN_N:
            return {"coast": round(_median([r["measure"]["coast"] for r in rows]), 2), "n": len(rows), "source": source}
    return None


def record(episode, data, records):
    """
    The hold record for one top-up: predicted from the earlier records, then
    measured. data is what store.read_samples returned.
    """
    samples = (data or {}).get("samples") or []
    band = tuner_core.outdoor_band(episode.get("outdoor_avg"))
    rec = {"schema": SCHEMA, "start": episode["start"], "room_id": episode.get("room_id"), "band": band,
           "kp": (episode.get("params") or {}).get("kp"), "valid": episode.get("valid")}
    if not samples:
        return {**rec, "block": None, "measure": {"reason": "no_samples"}, "prediction": None}
    m = measure(samples)
    rec["block"] = m.get("block")
    pred = model(records, rec["room_id"], rec["block"], band) if rec["block"] else None
    if pred and "coast" in m:
        pred = {**pred, "error": round(pred["coast"] - m["coast"], 2)}
    rec["prediction"] = pred
    rec["measure"] = m
    return rec


def summary(records, rooms):
    """
    Per room with coasts: per block the coasts, the model per band and the
    prediction errors. rooms is a list of (room_id, name). Returns a list of
    {room_id, room, top_ups, blocks: {block: {coasts, median, bands: {band: model}, errors}}}.
    """
    out = []
    for room_id, name in rooms:
        mine = [r for r in records if r.get("room_id") == room_id and "coast" in (r.get("measure") or {})]
        if not mine:
            continue
        blocks = {}
        for block, _, _ in BLOCKS:
            rows = [r for r in mine if r.get("block") == block]
            if not rows:
                continue
            bands = {band: model(records, room_id, block, band)
                     for band in tuner_core.BAND_NAMES if any(r.get("band") == band for r in rows)}
            errors = [r["prediction"]["error"] for r in rows if (r.get("prediction") or {}).get("error") is not None]
            blocks[block] = {
                "coasts": len(rows),
                "median": round(_median([r["measure"]["coast"] for r in rows[-MODEL_N:]]), 2),
                "bands": bands,
                "errors": errors[-MODEL_N:],
            }
        out.append({"room_id": room_id, "room": name, "top_ups": len(mine), "blocks": blocks})
    return out


def summary_line(per_room):
    """Evening report line: the coast after top-ups per room and time of day."""
    if not per_room:
        return None
    parts = []
    for r in per_room:
        bits = []
        for block, v in r["blocks"].items():
            text = f"{BLOCK_NAMES[block]} {v['median']:.2f} °C ({v['coasts']})"
            if v["errors"]:
                mean = sum(abs(e) for e in v["errors"]) / len(v["errors"])
                text += f", predicted within {mean:.2f}"
            bits.append(text)
        parts.append(f"{r['room']}, {r['top_ups']} top-ups: {'; '.join(bits)}")
    return "- Coast after top-ups (rise after the burner stops): " + "; ".join(parts)
