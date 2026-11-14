"""
progress - how far each learning feature is from stable
-------------------------------------------------------
Plain Python, no Home Assistant. Measures the stored records against the
thresholds in docs/experimental.md ("When a feature becomes
stable") and returns lines for the evening report. Keep the numbers
here and in the docs in step.
"""

from . import gas_core, night_core, tuner_core

# Gas per degree-day
GAS_DAYS = 365             # a full year of data holds a whole heating season

# Night cooldown model
NIGHTS = 30                # predicted nights judged
NIGHT_BANDS = 3            # spread over this many outdoor bands
NIGHT_MEAN_ERROR = 0.3     # degC, average absolute error
NIGHT_MAX_ERROR = 0.6      # degC, worst night

# Warm-up episodes and PID advice
PID_BANDS = 2              # outdoor bands with a confirmed change
PID_EPISODES_AFTER = 5     # valid episodes in that band after the change
PID_COMPARE_BEFORE = 5     # episodes before the change to compare with
# Nothing comparable before a change (schema or flow limit changed with it):
# the first PID_COMPARE_BEFORE episodes after it are the baseline, and the
# PID_EPISODES_AFTER that follow must hold steady against it.
PID_STEADY_OVERSHOOT = 0.1  # degC more average overshoot than the baseline, at most
PID_STEADY_RISE = 0.1       # fraction longer average warm-up than the baseline, at most


def gas_progress(summary):
    """Days of gas and outdoor statistics against a full year."""
    if summary is None:
        return {"done": False, "text": "Gas per degree-day: not set up"}
    days = summary.get("days", 0)
    text = f"Gas per degree-day: {min(days, GAS_DAYS)} of {GAS_DAYS} days of data"
    if summary.get("first"):
        text += " (since {})".format(summary["first"])
    rate = summary.get("rate")
    if rate is None:  # no boiler signals: no split, so no rate needed
        rate_ok = True
    elif rate["source"] == "default":
        rate_ok = False
        text += "; hot-water rate still the default ({} of {} minutes measured)".format(
            rate["minutes"], gas_core.RATE_MIN_MINUTES
        )
    else:
        rate_ok = True
        text += "; hot-water rate {}".format(rate["source"])
    return {"done": days >= GAS_DAYS and rate_ok, "text": text}


def night_progress(nights):
    """The last NIGHTS valid nights with a prediction: count, bands and errors."""
    judged = [n for n in nights if n.get("valid") and n.get("prediction_error") is not None][-NIGHTS:]
    if not judged:
        return {"done": False, "text": f"Night model: 0 of {NIGHTS} predicted nights"}
    errors = [abs(n["prediction_error"]) for n in judged]
    bands = {tuner_core.outdoor_band(n.get("outdoor_avg")) for n in judged} - {"unknown"}
    mean, worst = sum(errors) / len(errors), max(errors)
    done = (
        len(judged) >= NIGHTS
        and len(bands) >= NIGHT_BANDS
        and mean <= NIGHT_MEAN_ERROR
        and worst <= NIGHT_MAX_ERROR
    )
    text = (
        f"Night model: {len(judged)} of {NIGHTS} predicted nights, {min(len(bands), NIGHT_BANDS)} of {NIGHT_BANDS} outdoor bands, "
        f"average error {mean:.2f} (max {NIGHT_MEAN_ERROR}), worst {worst:.1f} (max {NIGHT_MAX_ERROR})"
    )
    return {"done": done, "text": text}


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _better(before, after):
    """Less overshoot or a faster warm-up on average."""
    for key in ("overshoot", "rise_min"):
        b, a = _mean([e.get(key) for e in before]), _mean([e.get(key) for e in after])
        if b is not None and a is not None and a < b:
            return True
    return False


def _steady(baseline, after):
    """Not worse than the baseline: overshoot and warm-up time within a small margin."""
    compared = False
    for key, worse in (
        ("overshoot", lambda b, a: a > b + PID_STEADY_OVERSHOOT),
        ("rise_min", lambda b, a: a > b * (1 + PID_STEADY_RISE)),
    ):
        b, a = _mean([e.get(key) for e in baseline]), _mean([e.get(key) for e in after])
        if b is None or a is None:
            continue
        if worse(b, a):
            return False
        compared = True
    return compared


def output_scale(record):
    """
    What the PID output (0 to 1) is multiplied by to give the flow request, in degC.

    With thermostat.yaml (schema 3 on) that is the flow limit (max_ch). Before
    schema 3 a recorded limit was not what the thermostat asked for: the PID
    output went to a 0 to 100 range and the boiler stopped at its own maximum.
    Without a limit the 0 to 100 range applies, as in tuner_core.limits().
    """
    cap = record.get("max_ch")
    if tuner_core.schema_of(record) >= 3 and cap and cap > 0:
        return float(cap)
    return 100.0


def effective_gains(record):
    """
    Kp, Ki and Kd times the output scale: degC of flow request per degC of error.

    A firmware change that rescales the PID output (thermostat.yaml 2026-11-07:
    output times the flow limit instead of 0 to 100, Kp and Ki times 2.5) keeps
    these the same, so it is no PID change (#132).
    """
    scale = output_scale(record)
    return {k: round(v * scale, 6) for k, v in sorted(record["params"].items())}


def _why_nothing_before(earlier, cap, schema):
    """Why no warm-up of a band before a change can be compared with the ones after it."""
    if not earlier:
        return "no warm-ups in this band before it"
    reasons = []
    if not any(tuner_core.schema_of(e) == schema for e in earlier):
        reasons.append("the record format")
    if not any(e.get("max_ch") == cap for e in earlier):
        reasons.append("the flow limit")
    if not reasons:  # each matches on one, none on both
        reasons = ["the flow limit or the record format"]
    return " and ".join(reasons) + " changed with it"


def pid_changes(episodes, room_id=None, room_name=None):
    """
    PID values changed (by hand or by autotune) between valid warm-ups of the followed room
    (judged against the room followed now: tuner_core.for_advice).
    Returns per outdoor band the last change: the warm-ups before it and after it,
    when it was and what changed.

    A change is a change of effective gains (effective_gains), not of the
    stored numbers: rescaling Kp and Ki along with the PID output is the same
    controller.

    There is one set of PID values for all weather, so a change counts in
    every band with a warm-up on the new values after it, not only in the
    band of the first warm-up after it.

    Before and after only hold warm-ups with the boiler flow limit (max_ch) of
    the band's first warm-up after the change: a lower limit alone slows a
    warm-up and cuts its overshoot, which would otherwise be credited to the
    PID. Records without max_ch (older ones, or the field not set) only
    compare with each other. The same goes for the schema: schema 2 ends the
    watch after reaching target at the first reheat, so it measures overshoot
    and dip differently, whatever the PID values are.
    """
    followed = [
        e for e in episodes
        if tuner_core.for_advice(e, room_id, room_name)
        and e.get("params") and None not in e["params"].values()
    ]
    gains = [effective_gains(e) for e in followed]
    by_band = {}
    for i in range(1, len(followed)):
        if gains[i] == gains[i - 1]:
            continue
        # Warm-ups on the new values, until the next change
        run = []
        for j in range(i, len(followed)):
            if gains[j] != gains[i]:
                break
            run.append(followed[j])
        old, new = followed[i - 1]["params"], followed[i]["params"]
        for band in dict.fromkeys(e["outdoor_band"] for e in run):
            first = next(e for e in run if e["outdoor_band"] == band)
            cap, schema = first.get("max_ch"), tuner_core.schema_of(first)

            def comparable(e, band=band, cap=cap, schema=schema):
                return (
                    e["outdoor_band"] == band and e.get("max_ch") == cap
                    and tuner_core.schema_of(e) == schema
                )

            before = [e for e in followed[:i] if comparable(e)][-PID_COMPARE_BEFORE:]
            after = [e for e in run if comparable(e)]
            change = {
                "before": before, "after": after,
                "date": str(followed[i].get("start", ""))[:10],
                "old": old, "new": new,
            }
            if not before:
                earlier = [e for e in followed[:i] if e["outdoor_band"] == band]
                change["why"] = _why_nothing_before(earlier, cap, schema)
            by_band[band] = change
    return by_band


def _what_changed(change):
    """Kp 0.7 -> 1.75, Ki 0.003 -> 0.0075: the values that changed."""
    old, new = change.get("old") or {}, change.get("new") or {}
    parts = [
        f"{k.capitalize()} {old[k]:g} → {new[k]:g}"
        for k in ("kp", "ki", "kd")
        if k in old and k in new and old[k] != new[k]
    ]
    return ", ".join(parts)


def _change_label(change):
    label = "the change of {}".format(change.get("date") or "unknown date")
    what = _what_changed(change)
    return f"{label} ({what})" if what else label


def _more(n):
    return "{} more warm-up{} needed".format(n, "" if n == 1 else "s")


def _band_progress(band, change):
    """(confirmed, text) for one band's last change."""
    before, after = change["before"], change["after"]
    if before:
        n = len(after)
        better = n > 0 and _better(before, after)
        confirmed = n >= PID_EPISODES_AFTER and better
        text = f"{band}: {min(n, PID_EPISODES_AFTER)} of {PID_EPISODES_AFTER} warm-ups after the change"
        if n:
            text += ", better" if better else ", not better"
            text += "" if n >= PID_EPISODES_AFTER else " so far"
        if n < PID_EPISODES_AFTER:
            text += f" ({_more(PID_EPISODES_AFTER - n)})"
        return confirmed, text
    # Nothing comparable before the change: judge against a baseline taken after it
    why = change.get("why") or "nothing comparable before it"
    baseline, rest = after[:PID_COMPARE_BEFORE], after[PID_COMPARE_BEFORE:]
    if len(baseline) < PID_COMPARE_BEFORE:
        needed = PID_COMPARE_BEFORE - len(baseline) + PID_EPISODES_AFTER
        return False, f"{band}: {len(baseline)} of {PID_COMPARE_BEFORE} warm-ups for a baseline ({_more(needed)}; nothing to compare with: {why})"
    n = len(rest)
    steady = n > 0 and _steady(baseline, rest)
    text = f"{band}: {min(n, PID_EPISODES_AFTER)} of {PID_EPISODES_AFTER} warm-ups after a baseline of {PID_COMPARE_BEFORE}"
    if n:
        text += ", steady" if steady else ", not steady"
        text += "" if n >= PID_EPISODES_AFTER else " so far"
    if n < PID_EPISODES_AFTER:
        text += f" ({_more(PID_EPISODES_AFTER - n)})"
    return n >= PID_EPISODES_AFTER and steady, text


def pid_progress(episodes, room_id=None, room_name=None):
    changes = pid_changes(episodes, room_id, room_name)
    head = f"PID advice: {{}} of {PID_BANDS} outdoor bands confirmed"
    if not changes:
        text = head.format(0) + " (no change applied yet)"
        return {"done": False, "text": text + "; check gas per degree-day did not get worse"}
    labels = {band: _change_label(c) for band, c in changes.items()}
    shared = len(set(labels.values())) == 1
    good, parts = 0, []
    for band, c in sorted(changes.items()):
        confirmed, part = _band_progress(band, c)
        good += confirmed
        parts.append(part if shared else f"{part}, for {labels[band]}")
    text = head.format(min(good, PID_BANDS))
    if shared:
        text += " for " + next(iter(labels.values()))
    text += ". " + "; ".join(parts)
    text += ". Check gas per degree-day did not get worse"
    return {"done": good >= PID_BANDS, "text": text}


FEATURES = (("gas", "Gas per degree-day"), ("night", "Night model"), ("pid", "PID advice"))


def statuses(gas_summary, nights, episodes, room_id=None, room_name=None):
    """{feature key: progress} for each feature; nights and episodes of the followed room."""
    nights = night_core.for_room(nights, room_id) if room_id else nights
    return {
        "gas": gas_progress(gas_summary),
        "night": night_progress(nights),
        "pid": pid_progress(episodes, room_id, room_name),
    }


def lines_from(status):
    """Report lines, one per feature, from statuses()."""
    return [
        "- " + status[key]["text"] + ("; ready to become stable" if status[key]["done"] else "")
        for key, _name in FEATURES
    ]


def maturity_events(before, status):
    """Lines for features whose ready-for-stable state changed since before ({key: done})."""
    events = []
    for key, name in FEATURES:
        if key in (before or {}) and before[key] != status[key]["done"]:
            events.append(f"- {name}: " + ("ready to become stable" if status[key]["done"] else "no longer ready for stable"))
    return events


def report_lines(gas_summary, nights, episodes, room_id=None, room_name=None):
    """Lines for the evening report, one per feature; nights and episodes of the followed room."""
    return lines_from(statuses(gas_summary, nights, episodes, room_id, room_name))
