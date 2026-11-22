"""Hold profile: coast after top-ups (#163): pure functions, no Home Assistant."""

from __future__ import annotations

from custom_components.cloudless_multiroom_thermostat.experimental import hold_core


def _top_up(*, hour: int = 11, burn: int = 7, coast: float = 0.3, after: int = 30, target: float = 18.0,
            dip: float = 0.15) -> list[dict]:
    """A warm room that dips, gets one burn back to target, then coasts up and cools again."""
    samples = []
    room = target - dip
    for i in range(burn + after):
        minute = i % 60
        t = f"2026-11-19T{hour + (i // 60):02d}:{minute:02d}:00+01:00"
        flame = i < burn
        if flame:
            room = target - dip + dip * (i + 1) / burn  # back at target as the flame stops
        elif i - burn <= 10:
            room = target + coast * (i - burn) / 10  # the coast, from target as the flame stops
        else:
            room -= 0.01
        samples.append({"t": t, "room": round(room, 2), "target": target, "flame": flame, "dhw": False,
                        "garden_paused": False, "flow_req": 40.0 if flame else 0.0, "water": 42.0})
    return samples


def test_measure_finds_the_coast() -> None:
    m = hold_core.measure(_top_up(coast=0.3))
    assert m["coast"] == 0.3
    assert m["at_off"] == 0.0
    assert m["dip"] == 0.13  # lowest room sample of the burn
    assert m["burn_min"] == 7
    assert m["flow_req_max"] == 40.0
    assert m["hour"] == 11 and m["block"] == "10_13"


def test_measure_refuses_what_it_cannot_judge() -> None:
    assert hold_core.measure([])["reason"] == "no_data"
    no_burn = [{**s, "flame": False} for s in _top_up()]
    assert hold_core.measure(no_burn)["reason"] == "no_burn"
    endless = [{**s, "flame": True} for s in _top_up()]
    assert hold_core.measure(endless)["reason"] == "burn_not_ended"
    assert hold_core.measure(_top_up(after=5))["reason"] == "too_short"
    samples = _top_up()
    for s in samples[1:5]:
        s["dhw"] = True
    assert hold_core.measure(samples)["reason"] == "hot_water"


def test_a_target_change_ends_the_data_but_keeps_the_coast_before_it() -> None:
    samples = _top_up(coast=0.3)
    for s in samples[25:]:
        s["target"] = 10.0  # schedule off after the coast was seen
    assert hold_core.measure(samples)["coast"] == 0.3
    samples = _top_up(coast=0.3)
    for s in samples[9:]:
        s["garden_paused"] = True  # window open right after the burn
    assert hold_core.measure(samples)["reason"] == "too_short"


def test_blocks() -> None:
    assert hold_core.block_of(7) == "0_10"
    assert hold_core.block_of(12) == "10_13"
    assert hold_core.block_of(14) == "13_15"
    assert hold_core.block_of(19) == "15_24"


def _ep(start: str, outdoor: float = 5.0) -> dict:
    return {"start": start, "room_id": "r1", "outdoor_avg": outdoor, "params": {"kp": 1.9}, "valid": True}


def test_each_top_up_is_predicted_from_the_earlier_ones() -> None:
    records: list[dict] = []
    for i in range(6):
        rec = hold_core.record(_ep(f"2026-11-1{i}T11:00:00+01:00"), {"samples": _top_up(coast=0.3)}, records)
        records.append(rec)
    assert [r["prediction"] is None for r in records] == [True] * 5 + [False]
    last = records[-1]["prediction"]
    assert last == {"coast": 0.3, "n": 5, "source": "cell", "error": 0.0}


def test_the_block_stands_in_until_the_band_has_enough() -> None:
    records = [hold_core.record(_ep(f"2026-11-1{i}T11:00:00+01:00", outdoor=5.0), {"samples": _top_up(coast=0.3)}, [])
               for i in range(5)]
    rec = hold_core.record(_ep("2026-11-20T11:00:00+01:00", outdoor=10.0), {"samples": _top_up(coast=0.5)}, records)
    assert rec["band"] == "8_15"
    assert rec["prediction"]["source"] == "block"
    assert rec["prediction"]["error"] == -0.2
    # the afternoon has no history: nothing to predict from
    rec = hold_core.record(_ep("2026-11-20T16:00:00+01:00"), {"samples": _top_up(hour=16)}, records)
    assert rec["prediction"] is None


def test_without_samples() -> None:
    rec = hold_core.record(_ep("2026-11-01T11:00:00+01:00"), None, [])
    assert rec["measure"] == {"reason": "no_samples"}
    assert rec["prediction"] is None


def test_summary_and_report_line() -> None:
    records: list[dict] = []
    for i in range(6):
        records.append(hold_core.record(_ep(f"2026-11-1{i}T11:00:00+01:00"), {"samples": _top_up(coast=0.3)}, records))
    records.append(hold_core.record(_ep("2026-11-17T16:00:00+01:00"), {"samples": _top_up(hour=16, coast=0.8)}, records))
    per_room = hold_core.summary(records, [("r1", "Living Room"), ("r2", "Bedroom")])
    assert len(per_room) == 1
    room = per_room[0]
    assert room["top_ups"] == 7
    assert room["blocks"]["10_13"]["coasts"] == 6
    assert room["blocks"]["10_13"]["median"] == 0.3
    assert room["blocks"]["15_24"]["median"] == 0.8
    line = hold_core.summary_line(per_room)
    assert line.startswith("- Coast after top-ups")
    assert "10:00 to 13:00 0.30 °C (6), predicted within 0.00" in line
    assert "after 15:00 0.80 °C (1)" in line
    assert hold_core.summary_line([]) is None
