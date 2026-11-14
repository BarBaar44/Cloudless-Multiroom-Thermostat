"""Progress of the experimental features towards stable."""

from __future__ import annotations

from custom_components.cloudless_multiroom_thermostat.experimental import progress

P1 = {"kp": 0.6, "ki": 0.002, "kd": 900}
P2 = {"kp": 0.6, "ki": 0.0018, "kd": 900}


def _night(day: int, error: float, outdoor: float) -> dict:
    return {"valid": True, "prediction_error": error, "outdoor_avg": outdoor, "end": f"2026-11-{day:02d}"}


def _ep(day: int, params: dict, overshoot: float, band: str = "0_8", room_class: str = "living") -> dict:
    return {
        "start": f"2026-11-{day:02d}T07:00:00",
        "valid": True,
        "room_class": room_class,
        "outdoor_band": band,
        "params": params,
        "overshoot": overshoot,
        "rise_min": 50,
    }


def test_gas_progress() -> None:
    assert "not set up" in progress.gas_progress(None)["text"]
    p = progress.gas_progress({"days": 40, "first": "2026-09-14"})
    assert p["text"].startswith("Gas per degree-day: 40 of 365 days of data (since 2026-09-14)")
    assert "rate" not in p["text"] and not p["done"]  # no boiler signals: no rate needed
    p = progress.gas_progress({"days": 365, "rate": {"rate": 0.019, "source": "default", "minutes": 20}})
    assert "still the default (20 of 60 minutes measured)" in p["text"] and not p["done"]
    p = progress.gas_progress({"days": 365, "rate": {"rate": 0.021, "source": "measured", "minutes": 80}})
    assert p["done"]


def test_night_progress_counts_and_errors() -> None:
    nights = [_night(1, 0.5, 4.0), _night(2, -0.2, 10.0), {"valid": False, "prediction_error": 3.0}]
    p = progress.night_progress(nights)
    assert "2 of 30 predicted nights, 2 of 3 outdoor bands" in p["text"]
    assert "average error 0.35" in p["text"] and "worst 0.5" in p["text"]
    assert not p["done"]
    assert "0 of 30" in progress.night_progress([])["text"]


def test_night_progress_done() -> None:
    temps = (-2.0, 4.0, 10.0)
    nights = [_night(1 + i % 28, 0.1, temps[i % 3]) for i in range(30)]
    assert progress.night_progress(nights)["done"]


def test_pid_progress_needs_change_by_hand() -> None:
    p = progress.pid_progress([_ep(1, P1, 0.6), _ep(2, P1, 0.5)])
    assert "0 of 2" in p["text"] and "no change applied yet" in p["text"]


def test_pid_progress_change_improves() -> None:
    episodes = [_ep(1, P1, 0.6), _ep(2, P1, 0.5)] + [_ep(3 + i, P2, 0.2) for i in range(5)]
    episodes.append(_ep(9, P2, 0.9, room_class="other"))  # other rooms do not count
    p = progress.pid_progress(episodes)
    assert "1 of 2 outdoor bands confirmed" in p["text"]
    assert "for the change of 2026-11-03 (Ki 0.002 → 0.0018)" in p["text"]
    assert "0_8: 5 of 5 warm-ups after the change, better." in p["text"]
    assert not p["done"]


def test_pid_progress_change_not_better() -> None:
    episodes = [_ep(1, P1, 0.3), _ep(2, {**P2, "kp": 0.4}, 0.6)]
    episodes[1]["rise_min"] = 70
    assert "0_8: 1 of 5 warm-ups after the change, not better so far (4 more warm-ups needed)" in progress.pid_progress(episodes)["text"]


def test_report_lines() -> None:
    lines = progress.report_lines(None, [], [])
    assert len(lines) == 3 and all(line.startswith("- ") for line in lines)


def test_pid_progress_compares_same_flow_limit() -> None:
    """A lower boiler flow limit alone cuts overshoot; it must not be credited to the PID change."""
    before = [{**_ep(1, P1, 0.6), "max_ch": 47.5}, {**_ep(2, P1, 0.5), "max_ch": 47.5}]
    after = [{**_ep(3 + i, P2, 0.2), "max_ch": 40.0} for i in range(5)]
    change = progress.pid_changes(before + after)["0_8"]
    assert change["before"] == [] and len(change["after"]) == 5
    text = progress.pid_progress(before + after)["text"]
    assert "0 of 2 outdoor bands confirmed" in text
    assert "0_8: 0 of 5 warm-ups after a baseline of 5 (5 more warm-ups needed)" in text  # the 5 after the change are the baseline

    # Same limit on both sides: compared as before
    before = [{**e, "max_ch": 40.0} for e in before]
    assert "0_8: 5 of 5 warm-ups after the change, better" in progress.pid_progress(before + after)["text"]


def test_pid_progress_compares_same_schema() -> None:
    before = [{**_ep(1, P1, 0.6), "schema": 1}, {**_ep(2, P1, 0.5), "schema": 1}]
    after = [{**_ep(3 + i, P2, 0.2), "schema": 2} for i in range(5)]
    change = progress.pid_changes(before + after)["0_8"]
    assert change["before"] == [] and len(change["after"]) == 5, "older records have no say"

    before = [{**e, "schema": 2} for e in before]
    change = progress.pid_changes(before + after)["0_8"]
    assert len(change["before"]) == 2 and len(change["after"]) == 5

def _room_ep(day: int, params: dict, overshoot: float, room_id: str, followed_then: str) -> dict:
    """An episode as recorded while followed_then was the room to follow."""
    other = room_id != followed_then
    return {
        **_ep(day, params, overshoot, room_class="other" if other else "living"),
        "room_id": room_id, "area": room_id.title(),
        "valid": not other, "invalid_reasons": ["other_room"] if other else [],
    }


def test_pid_progress_follows_the_room_followed_now() -> None:
    # Recorded while "a" was followed; then the room to follow became "b"
    episodes = [_room_ep(d, P1, 0.6, "b", "a") for d in range(1, 6)]
    episodes += [_room_ep(d, P2, 0.3, "b", "a") for d in range(6, 11)]
    episodes += [_room_ep(d, P1, 0.6, "a", "a") for d in range(11, 13)]
    by_b = progress.pid_changes(episodes, "b", "B")
    assert len(by_b["0_8"]["before"]) == 5 and len(by_b["0_8"]["after"]) == 5
    assert "0_8: 5 of 5 warm-ups after the change, better" in progress.pid_progress(episodes, "b", "B")["text"]
    # Room "a" now only has its own episodes, all with the same values
    assert progress.pid_changes(episodes, "a", "A") == {}


def test_report_lines_count_nights_of_the_followed_room() -> None:
    nights = [{**_night(d, 0.1, 5.0), "room_id": "b"} for d in range(1, 4)] + [_night(4, 0.1, 5.0)]
    lines = progress.report_lines(None, nights, [], "a", "A")
    assert "Night model: 1 of 30" in lines[1]


def test_one_change_counts_in_every_band() -> None:
    """One set of PID values for all weather: a change is judged in each band it ran in."""
    episodes = [_ep(d, P1, 0.6, band="0_8") for d in range(1, 6)]
    episodes += [_ep(d, P1, 0.7, band="below_0") for d in range(6, 11)]
    # One change by hand, then warm-ups in both bands
    episodes += [_ep(d, P2, 0.3, band="0_8" if d % 2 else "below_0") for d in range(11, 21)]
    changes = progress.pid_changes(episodes)
    assert sorted(changes) == ["0_8", "below_0"]
    assert all(len(c["before"]) == 5 and len(c["after"]) == 5 for c in changes.values())
    p = progress.pid_progress(episodes)
    assert p["done"] and "2 of 2 outdoor bands confirmed" in p["text"]


def test_a_later_change_replaces_the_earlier_one_per_band() -> None:
    p3 = {**P2, "kp": 0.5}
    episodes = [_ep(1, P1, 0.6), _ep(2, P2, 0.3), _ep(3, p3, 0.2), _ep(4, p3, 0.2)]
    change = progress.pid_changes(episodes)["0_8"]
    assert [e["params"] for e in change["after"]] == [p3, p3]
    assert [e["params"] for e in change["before"]] == [P1, P2]


def _schema_change(after_overshoots: list[float]) -> list[dict]:
    """A PID change that came with a schema bump: nothing before it is comparable (#96)."""
    before = [{**_ep(d, P1, 0.5), "schema": 2} for d in range(1, 4)]
    after = [{**_ep(4 + i, P2, o), "schema": 3} for i, o in enumerate(after_overshoots)]
    return before + after


def test_pid_progress_says_nothing_comparable_before() -> None:
    text = progress.pid_progress(_schema_change([0.2, 0.15, 0.1]))["text"]
    assert "0 of 2 outdoor bands confirmed" in text
    assert "0_8: 3 of 5 warm-ups for a baseline (7 more warm-ups needed; nothing to compare with: the record format changed with it)" in text


def test_pid_progress_baseline_then_steady_confirms() -> None:
    episodes = _schema_change([0.2] * 5 + [0.25] * 4)
    assert "0_8: 4 of 5 warm-ups after a baseline of 5, steady so far (1 more warm-up needed)" in progress.pid_progress(episodes)["text"]
    episodes = _schema_change([0.2] * 5 + [0.25] * 5)
    text = progress.pid_progress(episodes)["text"]
    assert "1 of 2 outdoor bands confirmed" in text and "0_8: 5 of 5 warm-ups after a baseline of 5, steady." in text


def test_pid_progress_baseline_not_steady() -> None:
    worse_overshoot = _schema_change([0.2] * 5 + [0.4] * 5)
    assert "0_8: 5 of 5 warm-ups after a baseline of 5, not steady." in progress.pid_progress(worse_overshoot)["text"]
    slower = _schema_change([0.2] * 10)
    for e in slower[-5:]:
        e["rise_min"] = 60  # 20% longer than the baseline's 50
    assert "0 of 2 outdoor bands confirmed" in progress.pid_progress(slower)["text"]


def _rescale(day: int, overshoot: float, schema: int, max_ch: float | None, params: dict, band: str = "0_8") -> dict:
    return {**_ep(day, params, overshoot, band=band), "schema": schema, "max_ch": max_ch}


OLD = {"kp": 0.7, "ki": 0.003, "kd": 0.0}  # PID output on a 0 to 100 range
NEW = {"kp": 1.75, "ki": 0.0075, "kd": 0.0}  # same PID, output times a 40 degC flow limit


def test_effective_gains_follow_the_output_scale() -> None:
    # Before schema 3 the recorded limit was not what the PID output was scaled by
    assert progress.output_scale({"schema": 2, "max_ch": 40.0}) == 100.0
    assert progress.output_scale({"schema": 3, "max_ch": 40.0}) == 40.0
    assert progress.output_scale({"schema": 3, "max_ch": None}) == 100.0
    assert progress.output_scale({}) == 100.0
    old = progress.effective_gains({"schema": 2, "max_ch": 40.0, "params": OLD})
    new = progress.effective_gains({"schema": 3, "max_ch": 40.0, "params": NEW})
    assert old == new == {"kd": 0.0, "ki": 0.3, "kp": 70.0}


def test_a_rescale_is_no_pid_change() -> None:
    """thermostat.yaml 2026-11-07: Kp and Ki times 2.5 with the output times 40 instead of 100 (#132)."""
    episodes = [_rescale(d, 0.4, 2, 40.0, OLD) for d in range(1, 4)]
    episodes += [_rescale(d, 0.1, 3, 40.0, NEW) for d in range(4, 14)]
    assert progress.pid_changes(episodes) == {}
    assert "no change applied yet" in progress.pid_progress(episodes)["text"]


def test_a_real_change_after_a_rescale_is_seen() -> None:
    episodes = [_rescale(d, 0.4, 2, 40.0, OLD) for d in range(1, 3)]
    episodes += [_rescale(d, 0.2, 3, 40.0, NEW) for d in range(3, 6)]
    episodes += [_rescale(d, 0.1, 3, 40.0, {**NEW, "kp": 1.9}) for d in range(6, 8)]
    change = progress.pid_changes(episodes)["0_8"]
    assert len(change["before"]) == 3 and len(change["after"]) == 2
    assert change["date"] == "2026-11-06"
    assert "for the change of 2026-11-06 (Kp 1.75 → 1.9)" in progress.pid_progress(episodes)["text"]


def test_report_says_why_nothing_is_comparable() -> None:
    p3 = {**NEW, "kp": 1.9}
    flow = [_rescale(1, 0.3, 3, 50.0, NEW), _rescale(2, 0.2, 3, 40.0, p3)]
    assert "the flow limit changed with it" in progress.pid_progress(flow)["text"]
    mild = [_rescale(1, 0.3, 3, 40.0, NEW), _rescale(2, 0.2, 3, 40.0, p3, band="8_15")]
    assert "no warm-ups in this band before it" in progress.pid_progress(mild)["text"]


def test_bands_on_different_changes_name_their_own() -> None:
    p3 = {**NEW, "kp": 1.9}
    episodes = [_rescale(1, 0.3, 3, 40.0, NEW), _rescale(2, 0.3, 3, 40.0, NEW, band="8_15")]
    episodes += [_rescale(3, 0.2, 3, 40.0, p3, band="8_15")]  # 8_15 last changed on 11-03
    episodes += [_rescale(4, 0.2, 3, 40.0, NEW)]  # back again: 0_8 last changed on 11-04
    text = progress.pid_progress(episodes)["text"]
    assert "8_15: " in text and ", for the change of 2026-11-03 (Kp 1.75 → 1.9)" in text
    assert ", for the change of 2026-11-04 (Kp 1.9 → 1.75)" in text


def test_a_band_confirmed_by_probing_counts() -> None:
    p = progress.pid_progress([], optimum={"0_8": "2026-11-20"})
    assert p["text"].startswith("PID advice: 1 of 2 outdoor bands confirmed. 0_8: confirmed by probing on 2026-11-20")
    assert not p["done"]
    p = progress.pid_progress([], optimum={"0_8": "2026-11-20", "below_0": "2026-12-03"})
    assert p["done"] and "2 of 2" in p["text"]
