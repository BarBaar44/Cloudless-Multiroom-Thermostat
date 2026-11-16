"""Heat-up model per room (#152): pure functions, no Home Assistant."""

from __future__ import annotations

import math

import pytest

from custom_components.cloudless_multiroom_thermostat.experimental import heatup_core


def _warm_up(dead: float, tau: float, gain: float, *, flow: float = 58.0, minutes: int = 150,
             room0: float = 18.0, target: float = 20.5, resolution: float = 0.01) -> list[dict]:
    """A first order plus dead time room heated by a constant requested flow."""
    a = math.exp(-1 / tau)
    b = gain * (1 - a)
    y = [0.0]
    for k in range(minutes - 1):
        y.append(a * y[-1] + b * ((flow - room0) if k >= dead else 0.0))
    return [
        {"t": f"m{i}", "room": round((room0 + v) / resolution) * resolution, "target": target,
         "flow_req": flow, "water": None, "dhw": False, "garden_paused": False}
        for i, v in enumerate(y)
    ]


@pytest.mark.parametrize(("dead", "tau", "gain"), [(10, 90, 0.06), (3, 40, 0.05), (20, 150, 0.08)])
def test_fit_recovers_known_rooms(dead: float, tau: float, gain: float) -> None:
    fit = heatup_core.fit(_warm_up(dead, tau, gain))
    assert abs(fit["dead_min"] - dead) <= 1
    assert fit["tau_min"] == pytest.approx(tau, rel=0.05)
    assert fit["gain"] == pytest.approx(gain, rel=0.05)


def test_fit_with_coarser_sensor() -> None:
    """A sensor in steps of 0.05 degC still lands near; 0.1 degC biases the time constant low (docs)."""
    fit = heatup_core.fit(_warm_up(10, 90, 0.06, resolution=0.05))
    assert abs(fit["dead_min"] - 10) <= 2
    assert fit["tau_min"] == pytest.approx(90, rel=0.2)
    assert fit["gain"] == pytest.approx(0.06, rel=0.2)


def test_fit_refuses_what_it_cannot_fit() -> None:
    assert heatup_core.fit([])["reason"] == "no_data"
    assert heatup_core.fit(_warm_up(5, 60, 0.05, minutes=10))["reason"] == "too_short"
    flat = [{**s, "room": 18.0} for s in _warm_up(5, 60, 0.05)]
    assert heatup_core.fit(flat)["reason"] == "no_rise"


def test_hot_water_and_window_cut_the_input() -> None:
    samples = _warm_up(5, 60, 0.05)
    samples[30]["garden_paused"] = True  # window open: the series stops there
    y, u, _ = heatup_core._series(samples)
    assert len(y) == 30
    samples = _warm_up(5, 60, 0.05)
    samples[10]["dhw"] = True  # hot water: no heat to the radiators
    _, u, _ = heatup_core._series(samples)
    assert u[10] == 0.0 and u[11] > 0


def test_records_predict_from_earlier_warm_ups_per_band() -> None:
    episode = {"start": "s", "room_id": "a", "outdoor_avg": 5.0}
    records = []
    for i in range(heatup_core.MIN_FITS):
        rec = heatup_core.record({**episode, "start": f"s{i}"}, {"samples": _warm_up(10, 90, 0.09)}, records)
        assert rec["prediction"] is None  # no model yet
        records.append(rec)
    rec = heatup_core.record({**episode, "start": "next"}, {"samples": _warm_up(10, 90, 0.09)}, records)
    assert rec["prediction"]["error_min"] is not None and abs(rec["prediction"]["error_min"]) <= 2
    # Another band has no model yet
    cold = heatup_core.record({**episode, "outdoor_avg": -3.0}, {"samples": _warm_up(10, 90, 0.09)}, records)
    assert cold["prediction"] is None
    assert heatup_core.record(episode, None, records)["fit"] == {"reason": "no_samples"}

    summary = heatup_core.summary([*records, rec], [("a", "Living"), ("b", "Office")])
    assert [r["room"] for r in summary] == ["Living"]
    line = heatup_core.summary_line(summary)
    assert line.startswith("- Heat-up model per room: Living (0 to 8 °C: dead time 10 min")
    assert "(1 predicted)" in line
    assert heatup_core.summary_line([]) is None
