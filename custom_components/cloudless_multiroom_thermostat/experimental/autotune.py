"""
autotune - apply the PID advice automatically, with guardrails
--------------------------------------------------------------
Plain Python, no Home Assistant. Only used when the option "Apply PID advice
automatically" is on; without it the advice stays a suggestion. runner.py
reads the PID numbers, calls decide() after each finished warm-up and writes
the value it returns.

Guardrails (see docs/experimental.md, "Applying the advice automatically"):
- one parameter per change, the advice's own 10% step, inside limits();
- a change is only made when the episodes the advice is based on all ran on
  the current values, so the last change has had its own warm-ups;
- after a change, EPISODES_AFTER valid warm-ups of the followed room in the
  same outdoor band, flow limit and schema decide: the problem the advice
  acted on must be smaller on average, or the change is reverted;
- a reverted change is never made again;
- values changed by hand (or by anything else) end the check without a revert:
  the user took over;
- a check that has no verdict after CHECK_MAX_DAYS (the weather moved to
  another band, few clean warm-ups) ends as inconclusive and the change stays:
  there is no evidence it made things worse, and the learning can go on.
Only warm-ups count (tuner_core.for_advice): top-ups are left out.

Probing (#132): advice only comes when something is wrong, so values that
are already good would never be tested. When PROBE_STREAK warm-ups in a row
ran on the current values and met every target (no verdict), Kp is stepped
up 10% as a probe; PROBE_EPISODES warm-ups in the same outdoor band, flow
limit and schema decide. Better (less overshoot or a faster warm-up, the
other not worse): kept. Otherwise reverted, and Kp is probed down the same
way. Neither direction better: the values are a confirmed optimum for that
band, flow limit and schema, and are not probed there again until they
change. A probe warm-up that misses a target reverts at once, and a probe
without a verdict after CHECK_MAX_DAYS is reverted too: nothing advised it.
Advice always comes first and ends a probe sequence that has not started.
"""

from datetime import datetime, timedelta
import math

from . import tuner_core

EPISODES_AFTER = 2  # valid warm-ups on the new values before a change is judged
CHECK_MAX_DAYS = 14  # a check without a verdict by then ends, and the change stays
LOG_KEEP = 50       # entries kept in the change log

PROBE_STREAK = 5        # warm-ups in a row on target, without advice, before a probe
PROBE_EPISODES = 5      # warm-ups on the probed value before it is judged
PROBE_BASELINE_MIN = 3  # warm-ups on the current values in the probe's group to compare with
PROBE_PARAM = "kp"
PROBE_METRICS = ("overshoot", "rise_min")
OPTIMUM_KEEP = 20       # confirmed optima kept

# What must get smaller for a change to stay, per verdict
METRICS = {
    "overshoot": ("overshoot",),
    "oscillating": ("flame_starts_per_hour", "undershoot"),
    "slow": ("rise_min",),
}


def same(a, b):
    """Two PID values equal within float noise (ESPHome numbers are float32)."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-9)


def same_params(a, b):
    if not a or not b:
        return False
    return all(same(a.get(k), b.get(k)) for k in ("kp", "ki", "kd"))


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def means(episodes, verdict):
    return {key: _mean([e.get(key) for e in episodes]) for key in METRICS[verdict]}


def improved(verdict, before, after):
    """True when one of the verdict's metrics went down and none went up."""
    down = up = False
    for key in METRICS[verdict]:
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            continue
        down = down or a < b
        up = up or a > b
    return down and not up


def usable(rec):
    """Advice that actually moves a value."""
    return bool(rec) and not rec.get("outside_range") and not rec.get("at_limit") and not same(rec["old"], rec["new"])


def _after(history, pending, room_id, room_name):
    return [
        e for e in history
        if e.get("start", "") > pending["at"]
        and tuner_core.for_advice(e, room_id, room_name)
        and same_params(e.get("params"), pending["params_after"])
        and e["outdoor_band"] == pending["band"]
        and e.get("max_ch") == pending["max_ch"]
        and tuner_core.schema_of(e) == pending["schema"]
    ]


def _entry(kind, at, param, old, new, why):
    return {"at": at, "action": kind, "param": param, "old": old, "new": new, "why": why}


def decide(history, params, rec, state, now, *, room_id=None, room_name=None, probe=False, round_value=None):
    """
    What to do after a finished warm-up.

    history: all episode records, params: the PID values now, rec: the advice
    from tuner_core.recommend (rounded to the number's step by the caller),
    state: the stored autotune state ({} at first), now: ISO time.
    Returns (action, new_state). action is None or
    {"action": "apply" | "revert" | "probe", "param", "value", "old", "why"};
    new_state assumes the write succeeds (the caller keeps the old state if it
    fails). probe: also probe values that get no advice (see the module
    docstring); round_value(rec) rounds a probe step like the advice (the
    number's step), returning a rec that is not usable() when it can't move.
    """
    state = {
        "pending": state.get("pending"),
        "reverted": list(state.get("reverted", [])),
        "log": list(state.get("log", [])),
        "probe_next": state.get("probe_next"),
        "optimum": list(state.get("optimum", [])),
    }

    def done(action):
        state["log"] = state["log"][-LOG_KEEP:]
        return action, state

    pending = state["pending"]
    if pending:
        if not same_params(params, pending["params_after"]):
            state["pending"] = None
            state["log"].append(_entry(
                "dropped", now, pending["param"], pending["old"], pending["new"], "values changed outside the integration"
            ))
            return done(None)
        if pending.get("probe"):
            return done(_judge_probe(state, pending, history, now, room_id, room_name))
        after = _after(history, pending, room_id, room_name)
        if len(after) < EPISODES_AFTER:
            if datetime.fromisoformat(now) - datetime.fromisoformat(pending["at"]) < timedelta(days=CHECK_MAX_DAYS):
                return done(None)
            state["pending"] = None
            state["log"].append(_entry(
                "inconclusive", now, pending["param"], pending["old"], pending["new"],
                f"{len(after)} of {EPISODES_AFTER} warm-ups in {CHECK_MAX_DAYS} days, change kept",
            ))
            return done(None)
        state["pending"] = None
        if improved(pending["verdict"], pending["before"], means(after, pending["verdict"])):
            state["log"].append(_entry("kept", now, pending["param"], pending["old"], pending["new"], "better after the change"))
        else:
            state["reverted"].append({"param": pending["param"], "old": pending["old"], "new": pending["new"]})
            state["log"].append(_entry("reverted", now, pending["param"], pending["new"], pending["old"], "not better after the change"))
            return done({
                "action": "revert", "param": pending["param"], "value": pending["old"],
                "old": pending["new"], "why": "not better after the change",
            })

    if not usable(rec):
        if probe:
            return done(_maybe_probe(state, history, params, now, room_id, room_name, round_value))
        return done(None)
    state["probe_next"] = None  # advice comes first
    if not all(same_params(p, params) for p in rec.get("group_params", [])):
        return done(None)  # the advice is (partly) based on older values
    for r in state["reverted"]:
        if r["param"] == rec["param"] and same(r["old"], rec["old"]) and same(r["new"], rec["new"]):
            return done(None)  # tried before and made it worse
    group = [e for e in history if tuner_core.for_advice(e, room_id, room_name)]
    group = [
        e for e in group
        if e["outdoor_band"] == rec["band"] and e.get("max_ch") == rec["max_ch"]
        and tuner_core.schema_of(e) == rec["schema"]
    ][-tuner_core.CONSISTENT_EPISODES:]
    state["pending"] = {
        "param": rec["param"], "old": rec["old"], "new": rec["new"], "verdict": rec["verdict"],
        "params_after": {**params, rec["param"]: rec["new"]},
        "band": rec["band"], "max_ch": rec["max_ch"], "schema": rec["schema"],
        "before": means(group, rec["verdict"]), "at": now,
    }
    state["log"].append(_entry("applied", now, rec["param"], rec["old"], rec["new"], rec["why"]))
    return done({"action": "apply", "param": rec["param"], "value": rec["new"], "old": rec["old"], "why": rec["why"]})


def _probe_means(episodes):
    return {key: _mean([e.get(key) for e in episodes]) for key in PROBE_METRICS}


def probe_better(before, after):
    """Less overshoot or a faster warm-up on average, and the other one not worse."""
    down = up = False
    for key in PROBE_METRICS:
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            continue
        down = down or a < b
        up = up or a > b
    return down and not up


def _group(e):
    return e["outdoor_band"], e.get("max_ch"), tuner_core.schema_of(e)


def _confirmed(state, params, group):
    return any(
        same_params(o["params"], params) and (o["band"], o["max_ch"], o["schema"]) == group
        for o in state["optimum"]
    )


def _streak(history, params, room_id, room_name):
    """The last PROBE_STREAK warm-ups, when all ran on params and met every target; else None."""
    last = [e for e in history if tuner_core.for_advice(e, room_id, room_name)][-PROBE_STREAK:]
    if len(last) < PROBE_STREAK:
        return None
    if all(same_params(e.get("params"), params) and tuner_core.verdict(e) is None for e in last):
        return last
    return None


def _start_probe(state, params, direction, group, before, now, round_value):
    """Pending state and action for a probe step, or None when the step can't move (limit)."""
    old = params[PROBE_PARAM]
    factor = 1 + tuner_core.STEP if direction == "up" else 1 - tuner_core.STEP
    step = {"param": PROBE_PARAM, "old": old, "new": round(old * factor, 5), "max_ch": group[1]}
    low, high = tuner_core.limits(PROBE_PARAM, group[1])
    if not low <= step["new"] <= high:
        return None
    if round_value:
        step = round_value(step)
    if not usable(step):
        return None
    why = f"probe {direction}: {PROBE_STREAK} warm-ups on target without advice"
    state["pending"] = {
        "probe": direction, "param": PROBE_PARAM, "old": old, "new": step["new"], "verdict": None,
        "params_after": {**params, PROBE_PARAM: step["new"]},
        "band": group[0], "max_ch": group[1], "schema": group[2], "before": before, "at": now,
    }
    state["log"].append(_entry("probe", now, PROBE_PARAM, old, step["new"], why))
    return {"action": "probe", "param": PROBE_PARAM, "value": step["new"], "old": old, "why": why}


def _optimum(state, params, group, now, why):
    state["optimum"] = [
        o for o in state["optimum"]
        if not (same_params(o["params"], params) and (o["band"], o["max_ch"], o["schema"]) == group)
    ]
    state["optimum"].append({"params": dict(params), "band": group[0], "max_ch": group[1], "schema": group[2], "at": now})
    state["optimum"] = state["optimum"][-OPTIMUM_KEEP:]
    state["log"].append(_entry("optimum", now, PROBE_PARAM, params[PROBE_PARAM], params[PROBE_PARAM], why))


def _maybe_probe(state, history, params, now, room_id, room_name, round_value):
    """Start the next probe step when the values get no advice; the action, or None."""
    nxt = state.get("probe_next")
    if nxt:
        state["probe_next"] = None
        if not same_params(params, nxt["params"]):
            return None  # values changed since: start over with a new streak
        group = (nxt["band"], nxt["max_ch"], nxt["schema"])
        action = _start_probe(state, params, nxt["direction"], group, nxt["before"], now, round_value)
        if action is None:
            _optimum(state, params, group, now, "not better up, down is at the limit")
        return action
    streak = _streak(history, params, room_id, room_name)
    if not streak:
        return None
    group = _group(streak[-1])
    if _confirmed(state, params, group):
        return None
    baseline = [
        e for e in history
        if tuner_core.for_advice(e, room_id, room_name) and _group(e) == group
        and same_params(e.get("params"), params)
    ][-PROBE_EPISODES:]
    if len(baseline) < PROBE_BASELINE_MIN:
        return None
    before = _probe_means(baseline)
    return (
        _start_probe(state, params, "up", group, before, now, round_value)
        or _start_probe(state, params, "down", group, before, now, round_value)
    )


def _judge_probe(state, pending, history, now, room_id, room_name):
    """Keep, revert or wait on a probe step; the revert action or None."""
    after = _after(history, pending, room_id, room_name)
    missed = next((tuner_core.verdict(e) for e in after if tuner_core.verdict(e)), None)
    if not missed and len(after) < PROBE_EPISODES:
        if datetime.fromisoformat(now) - datetime.fromisoformat(pending["at"]) < timedelta(days=CHECK_MAX_DAYS):
            return None
        why = f"probe {pending['probe']}: {len(after)} of {PROBE_EPISODES} warm-ups in {CHECK_MAX_DAYS} days, old value back"
        state["pending"] = None
        state["log"].append(_entry("reverted", now, pending["param"], pending["new"], pending["old"], why))
        return {"action": "revert", "param": pending["param"], "value": pending["old"], "old": pending["new"], "why": why}
    state["pending"] = None
    if not missed and probe_better(pending["before"], _probe_means(after)):
        state["log"].append(_entry(
            "kept", now, pending["param"], pending["old"], pending["new"], f"probe {pending['probe']}: better"
        ))
        return None
    why = f"probe {pending['probe']}: " + (f"a warm-up gave {missed}" if missed else "not better")
    state["log"].append(_entry("reverted", now, pending["param"], pending["new"], pending["old"], why))
    params = {**pending["params_after"], pending["param"]: pending["old"]}
    group = (pending["band"], pending["max_ch"], pending["schema"])
    if pending["probe"] == "up":
        state["probe_next"] = {
            "direction": "down", "params": params, "band": group[0], "max_ch": group[1],
            "schema": group[2], "before": pending["before"],
        }
    else:
        _optimum(state, params, group, now, "no better value up or down")
    return {"action": "revert", "param": pending["param"], "value": pending["old"], "old": pending["new"], "why": why}


def optimum_bands(state):
    """{band: date} of the confirmed optima (see _optimum), the latest per band."""
    return {o["band"]: o["at"][:10] for o in (state or {}).get("optimum", [])}


def is_reverted(state, rec):
    return usable(rec) and any(
        r["param"] == rec["param"] and same(r["old"], rec["old"]) and same(r["new"], rec["new"])
        for r in (state or {}).get("reverted", [])
    )


def status_line(state, history, room_id=None, room_name=None):
    """The check in progress, for the report; None when nothing is pending."""
    pending = (state or {}).get("pending")
    if not pending:
        return None
    n = len(_after(history, pending, room_id, room_name))
    what = "Probing ({})".format(pending["probe"]) if pending.get("probe") else "Checking"
    needed = PROBE_EPISODES if pending.get("probe") else EPISODES_AFTER
    return "- {} {} {} -> {} (since {}): {} of {} warm-ups in band {}".format(
        what, pending["param"], pending["old"], pending["new"], pending["at"][:16].replace("T", " "),
        min(n, needed), needed, pending["band"],
    )


def log_lines(state, day):
    """Changes made, probed, kept, reverted or dropped, and optima confirmed, on day (YYYY-MM-DD)."""
    return [
        "- {} optimum: {} {} confirmed ({})".format(e["at"][11:16], e["param"], e["old"], e["why"])
        if e["action"] == "optimum"
        else "- {} {}: {} {} -> {} ({})".format(
            e["at"][11:16], e["action"], e["param"], e["old"], e["new"], e["why"]
        )
        for e in (state or {}).get("log", []) if e["at"][:10] == day
    ]
