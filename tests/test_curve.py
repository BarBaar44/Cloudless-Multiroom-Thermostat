"""Heating curve: flow limit per outdoor band (#167): pure functions, no Home Assistant."""

from __future__ import annotations

from custom_components.cloudless_multiroom_thermostat.experimental import curve_core

ROOM = "living"


def _ep(start: str, *, kind: str = "top_up", room_id: str = ROOM, target: float = 20.0, burn: int = 6,
        water: float | None = 40.0, outdoor: float = 5.0, max_ch: float = 40.0, **extra) -> dict:
    """An episode record as tuner_core stores it; kind decides the start temperature."""
    return {
        "start": start, "room_id": room_id, "target": target,
        "start_temp": target - (0.2 if kind == "top_up" else 2.0),
        "outdoor_avg": outdoor, "max_ch": max_ch, "flame_on_min": burn, "dhw_min": 0,
        "water_peak": water, "low_load": False, "valid": True, "schema": 3, **extra,
    }


def _day(day: int, *, gap: int = 60, burn: int = 6, outdoor: float = 5.0, water: float = 40.0) -> list[dict]:
    """Five top-ups an hour apart on one day: four hold intervals."""
    return [_ep(f"2026-11-{day:02d}T{10 + i * gap // 60:02d}:{i * gap % 60:02d}:00+01:00",
                burn=burn, outdoor=outdoor, water=water) for i in range(5)]


def test_interval_turns_duty_into_the_flow_that_holds() -> None:
    first = _ep("2026-11-20T10:00:00+01:00", burn=6, water=40.0)
    second = _ep("2026-11-20T11:00:00+01:00")
    m = curve_core.interval(first, second)
    assert m["gap_min"] == 60 and m["burn_min"] == 6 and m["duty"] == 0.1
    # 10% of the time at 40 degC water, room at 20: a steady 22 degC would hold it
    assert m["hold_flow"] == 22.0


def test_interval_prefers_the_water_at_flame_off_and_leaves_out_hot_water() -> None:
    first = _ep("2026-11-20T10:00:00+01:00", burn=8, water=45.0, dhw_min=2)
    second = _ep("2026-11-20T11:00:00+01:00")
    hold = {"measure": {"burn_min": 6, "water_at_off": 38.0}}
    m = curve_core.interval(first, second, hold)
    assert m["burn_min"] == 6 and m["water"] == 38.0
    assert m["hold_flow"] == 21.8


def test_interval_refuses_what_is_not_a_hold() -> None:
    first = _ep("2026-11-20T10:00:00+01:00")
    assert curve_core.interval(first, _ep("2026-11-20T11:00:00+01:00", kind="warm_up"))["reason"] == "not_holding"
    assert curve_core.interval(first, _ep("2026-11-20T11:00:00+01:00", target=21.0))["reason"] == "target_changed"
    assert curve_core.interval(first, _ep("2026-11-20T10:05:00+01:00"))["reason"] == "gap"
    assert curve_core.interval(first, _ep("2026-11-20T14:00:00+01:00"))["reason"] == "gap"
    low = _ep("2026-11-20T10:00:00+01:00", low_load=True)
    assert curve_core.interval(low, _ep("2026-11-20T11:00:00+01:00"))["reason"] == "low_load"
    shower = {"measure": {"reason": "hot_water"}}
    assert curve_core.interval(first, _ep("2026-11-20T11:00:00+01:00"), shower)["reason"] == "hot_water"
    no_flame = _ep("2026-11-20T10:00:00+01:00", burn=0)
    assert curve_core.interval(no_flame, _ep("2026-11-20T11:00:00+01:00"))["reason"] == "no_data"


def test_pairs_follow_each_room_on_its_own() -> None:
    eps = [
        _ep("2026-11-20T10:00:00+01:00"),
        _ep("2026-11-20T10:30:00+01:00", room_id="office"),
        _ep("2026-11-20T11:00:00+01:00"),
        _ep("2026-11-20T12:00:00+01:00", kind="warm_up"),
        _ep("2026-11-20T13:00:00+01:00"),
    ]
    pairs = [(a["start"][11:16], b["start"][11:16]) for a, b in curve_core.pairs(eps)]
    # The office top-up has no next episode yet; a warm-up never starts a pair
    assert pairs == [("10:00", "11:00"), ("11:00", "12:00")]


def _records(eps: list[dict]) -> list[dict]:
    records: list[dict] = []
    for first, second in curve_core.pairs(eps):
        records.append(curve_core.record(first, second, None, records))
    return records


def test_each_hold_is_predicted_from_the_earlier_ones_in_its_band() -> None:
    records = _records(_day(18) + _day(19))
    holds = [r for r in records if "hold_flow" in r]
    # 4 per day; the night between the days is too long a gap
    assert len(holds) == 8 and records[4]["reason"] == "gap"
    assert all(r["prediction"] is None for r in holds[:5])
    assert holds[5]["prediction"] == {"hold_flow": 22.0, "n": 5, "error": 0.0}
    cold = _records(_day(18) + _day(19, outdoor=-2.0))
    assert all(r["prediction"] is None for r in cold if r["band"] == "below_0")


def test_suggestion_is_hold_flow_plus_headroom() -> None:
    eps = _day(17) + _day(18) + [_ep("2026-11-19T07:00:00+01:00", kind="warm_up", flow_req_avg=24.0)]
    s = curve_core.summary(_records(eps), eps, ROOM, "Living Room")
    v = s["bands"]["0_8"]
    assert s["limit"] == 40.0 and v["holds"] == 8 and v["hold_flow"] == 22.0
    assert v["use"] == 0.6 and v["warm_ups"] == 1
    assert v["suggested"] == 27.0 and v["why"] == "hold_flow"
    line = curve_core.summary_line(s)
    assert line.startswith("- Heating curve (learned, never applied): Living Room, now 40 °C.")
    assert "0 to 8 °C: holds at 22 °C (8), predicted within 0.0, warm-ups ask 60% of the limit (1), suggested limit 27 °C" in line


def test_never_suggests_less_while_warm_ups_use_the_full_limit() -> None:
    eps = _day(17) + _day(18) + [_ep("2026-11-19T07:00:00+01:00", kind="warm_up", flow_req_avg=38.0)]
    v = curve_core.summary(_records(eps), eps, ROOM, "Living Room")["bands"]["0_8"]
    assert v["use"] == 0.95
    assert v["suggested"] == 40.0 and v["why"] == "warm_ups_use_the_limit"


def test_no_suggestion_before_enough_holds() -> None:
    eps = _day(18)
    s = curve_core.summary(_records(eps), eps, ROOM, "Living Room")
    v = s["bands"]["0_8"]
    assert v["holds"] == 4 and v["suggested"] is None
    assert "suggested" not in curve_core.summary_line(s)
    assert curve_core.summary([], [], ROOM, "Living Room") is None


def test_suggestion_stays_inside_the_flow_limit_range() -> None:
    assert curve_core._round_limit(21.2) == 25.0
    assert curve_core._round_limit(31.2) == 31.5
    assert curve_core._round_limit(95.0) == 80.0
