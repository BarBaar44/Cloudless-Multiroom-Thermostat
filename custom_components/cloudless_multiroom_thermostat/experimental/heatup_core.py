"""
heatup_core - a heat-up model per room (#152, observe only)
------------------------------------------------------------
Plain Python, no Home Assistant. Fits a first order plus dead time model to
the minute samples of each warm-up, kept since 1.8.3 (#135 step 1):

    tau * dy/dt = -y + gain * u(t - dead)

y is the room's rise above its start temperature, u the flow (the requested
flow when known, else the flow water temperature) above that start
temperature, both in degC. dead and tau in minutes; gain is the room rise per
degC of flow at steady state.

Each warm-up is first predicted with the room's model from earlier warm-ups
in the same outdoor band (its own input, so the prediction tests the room,
not the PID), then fitted itself. Nothing here changes the heating; gains
calculated from the model are #135 steps 3 and 4, after v2 with #82.
"""

import math

from . import tuner_core

SCHEMA = 1
MAX_DEAD_MIN = 40          # dead times tried, 0 to this many minutes
MIN_SAMPLES = 20           # minutes of usable data for a fit
MIN_RISE = 0.3             # degC the room must rise for a fit
AFTER_REACH_MIN = 20       # minutes kept after the room reaches its target
MIN_FITS = 5               # fitted warm-ups per room and band before it predicts
MODEL_FITS = 7             # median over this many recent fits
TAU_RANGE = (5.0, 1440.0)  # minutes; a fit outside is not physical here


def _series(samples):
    """
    (y, u, target_rise) from the episode's minute samples, up to
    AFTER_REACH_MIN after the room reaches its target, stopped at a window
    or target change. None when there is nothing to fit.
    """
    if not samples or samples[0].get("room") is None or samples[0].get("target") is None:
        return None
    room0, target = samples[0]["room"], samples[0]["target"]
    use_request = any(s.get("flow_req") is not None for s in samples)
    y, u, reached_at = [], [], None
    for i, s in enumerate(samples):
        if s.get("room") is None or s.get("garden_paused") or s.get("target") != target:
            break
        flow = s.get("flow_req") if use_request else s.get("water")
        if s.get("dhw") or flow is None:
            flow = room0  # no heat to the radiators this minute
        y.append(s["room"] - room0)
        u.append(max(flow - room0, 0.0))
        if reached_at is None and s["room"] >= target:
            reached_at = i
        if reached_at is not None and i - reached_at >= AFTER_REACH_MIN:
            break
    return (y, u, target - room0) if y else None


def _fit_dead(y, u, dead):
    """
    Least squares a and b in y[k+1] = a*y[k] + b*u[k-dead]; returns
    (a, b, sse) or None. Before the start no heat went in, so u is 0 there:
    that is what makes the dead time visible.
    """
    syy = syu = suu = sy1y = sy1u = 0.0
    rows = []
    for k in range(len(y) - 1):
        yk, uk, y1 = y[k], (u[k - dead] if k >= dead else 0.0), y[k + 1]
        syy += yk * yk
        syu += yk * uk
        suu += uk * uk
        sy1y += y1 * yk
        sy1u += y1 * uk
        rows.append((yk, uk, y1))
    det = syy * suu - syu * syu
    if len(rows) < MIN_SAMPLES or det <= 0:
        return None
    a = (sy1y * suu - sy1u * syu) / det
    b = (sy1u * syy - sy1y * syu) / det
    sse = sum((y1 - a * yk - b * uk) ** 2 for yk, uk, y1 in rows)
    return a, b, sse


def fit(samples):
    """
    Fit dead time, time constant and gain to one warm-up's samples.
    Returns {dead_min, tau_min, gain, minutes, rmse} or {"reason": ...}.
    """
    series = _series(samples)
    if series is None:
        return {"reason": "no_data"}
    y, u, _ = series
    if len(y) < MIN_SAMPLES + 1:
        return {"reason": "too_short"}
    if max(y) < MIN_RISE:
        return {"reason": "no_rise"}
    if max(u) <= 0:
        return {"reason": "no_flow"}
    best = None
    for dead in range(0, min(MAX_DEAD_MIN, len(y) - MIN_SAMPLES) + 1):
        r = _fit_dead(y, u, dead)
        if r is None:
            continue
        a, b, sse = r
        if not 0 < a < 1 or b <= 0:
            continue
        tau = -1 / math.log(a)
        if not TAU_RANGE[0] <= tau <= TAU_RANGE[1]:
            continue
        n = len(y) - 1
        if best is None or sse < best[3]:
            best = (dead, tau, b / (1 - a), sse, n)
    if best is None:
        return {"reason": "no_fit"}
    dead, tau, gain, sse, n = best
    return {
        "dead_min": dead, "tau_min": round(tau, 1), "gain": round(gain, 4),
        "minutes": len(y), "rmse": round(math.sqrt(sse / n), 3),
    }


def simulate(model, u):
    """Room rise per minute for input u with the model's dead time, time constant and gain."""
    a = math.exp(-1 / model["tau_min"])
    b = model["gain"] * (1 - a)
    dead = int(model["dead_min"])
    y = [0.0]
    for k in range(len(u) - 1):
        y.append(a * y[-1] + b * (u[k - dead] if k >= dead else 0.0))
    return y


def _reach(y, rise):
    return next((i for i, v in enumerate(y) if v >= rise), None)


def predict(model, samples):
    """
    What the model says this warm-up does with its own input: minutes until
    the target is reached and the peak rise, against what happened.
    Returns {reach_min, peak, actual_reach_min, actual_peak, error_min} or None.
    """
    series = _series(samples)
    if model is None or series is None:
        return None
    y, u, rise = series
    sim = simulate(model, u)
    reach, actual = _reach(sim, rise), _reach(y, rise)
    return {
        "reach_min": reach, "peak": round(max(sim), 2),
        "actual_reach_min": actual, "actual_peak": round(max(y), 2),
        "error_min": reach - actual if reach is not None and actual is not None else None,
    }


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def room_model(records, room_id, band):
    """Median of the room's last MODEL_FITS fits in this outdoor band, after MIN_FITS; else None."""
    fits = [r["fit"] for r in records
            if r.get("room_id") == room_id and r.get("band") == band and "tau_min" in (r.get("fit") or {})]
    fits = fits[-MODEL_FITS:]
    if len(fits) < MIN_FITS:
        return None
    return {key: _median([f[key] for f in fits]) for key in ("dead_min", "tau_min", "gain")} | {"fits": len(fits)}


def record(episode, data, records):
    """
    The heat-up record for one episode: predicted with the model from the
    earlier records, then fitted. data is what store.read_samples returned.
    """
    samples = (data or {}).get("samples") or []
    band = tuner_core.outdoor_band(episode.get("outdoor_avg"))
    rec = {"schema": SCHEMA, "start": episode["start"], "room_id": episode.get("room_id"), "band": band}
    if not samples:
        return {**rec, "fit": {"reason": "no_samples"}, "prediction": None}
    rec["prediction"] = predict(room_model(records, rec["room_id"], band), samples)
    rec["fit"] = fit(samples)
    return rec


def summary(records, rooms):
    """
    Per room with fits: the model per band and the prediction errors.
    rooms is a list of (room_id, name). Returns a list of
    {room_id, room, bands: {band: {model, errors}}}.
    """
    out = []
    for room_id, name in rooms:
        mine = [r for r in records if r.get("room_id") == room_id]
        bands = {}
        for band in tuner_core.BAND_NAMES:
            fits = [r for r in mine if r.get("band") == band and "tau_min" in (r.get("fit") or {})]
            if not fits:
                continue
            errors = [r["prediction"]["error_min"] for r in mine if r.get("band") == band
                      and (r.get("prediction") or {}).get("error_min") is not None]
            bands[band] = {"fits": len(fits), "model": room_model(records, room_id, band), "errors": errors[-MODEL_FITS:]}
        if bands:
            out.append({"room_id": room_id, "room": name, "bands": bands})
    return out


def summary_line(per_room):
    """Evening report line: the heat-up model per room and band."""
    if not per_room:
        return None
    parts = []
    for r in per_room:
        bits = []
        for band, v in r["bands"].items():
            label = tuner_core.BAND_NAMES[band] + " °C"
            m = v["model"]
            if m is None:
                bits.append(f"{label}: {v['fits']} of {MIN_FITS} warm-ups fitted")
                continue
            text = f"{label}: dead time {m['dead_min']:g} min, time constant {m['tau_min']:g} min, gain {m['gain']:.3f}"
            if v["errors"]:
                mean = sum(abs(e) for e in v["errors"]) / len(v["errors"])
                text += f", reaches target within {mean:.0f} min of the prediction ({len(v['errors'])} predicted)"
            bits.append(text)
        parts.append(f"{r['room']} ({'; '.join(bits)})")
    return "- Heat-up model per room: " + "; ".join(parts)
