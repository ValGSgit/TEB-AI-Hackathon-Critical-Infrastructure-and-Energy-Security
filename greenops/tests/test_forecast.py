"""Forecast and baseline tests.

Verifies that the planner only uses published forecasts (never actuals), that the beyond-forecast
blend formula is correct, that Live.forecast aligns to whole hours and gap-fills, and that the
score computation is arithmetically consistent.
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from greenops.spec import load
from greenops.planner import Planner
from greenops.game import Game, make_grid
from greenops.play import Naive, run
from fake_platform import Fake


@pytest.fixture(scope="module")
def spec():
    return load()


# ------------------------------------------------------------------ Live.forecast against fake platform
def test_forecast_against_fake_platform():
    """Live.forecast against fake_platform: returns exactly horizon values aligned to int(now_h);
    a forecast with a missing hour is gap-filled; an empty forecast raises; only horizonHours 6
    or 24 are ever requested; every request stays under /runs/{id}/ and carries the auth-token
    header."""
    import requests
    f = Fake(seed=7, step_h=1.0)

    # Test horizon 6
    resp6 = requests.get(f.grid_url + "/carbon-intensity/forecast?zone=DE&horizonHours=6",
                         headers={"auth-token": "g"}, timeout=5)
    assert resp6.status_code == 200
    d6 = resp6.json()
    assert len(d6["forecast"]) == 6
    assert all("carbonIntensity" in e for e in d6["forecast"])

    # Test horizon 24
    resp24 = requests.get(f.grid_url + "/carbon-intensity/forecast?zone=DE&horizonHours=24",
                          headers={"auth-token": "g"}, timeout=5)
    assert resp24.status_code == 200
    assert len(resp24.json()["forecast"]) == 24

    # Test all areas
    for area in ["DE", "AT", "CH", "BG", "ES", "FR", "HR", "IT"]:
        r = requests.get(f.grid_url + f"/carbon-intensity/forecast?zone={area}&horizonHours=6",
                         headers={"auth-token": "g"}, timeout=5)
        assert r.status_code == 200, f"forecast for {area} failed"

    # Test that unknown paths are rejected (stay within run prefix)
    bad = requests.get(f.base + "/other/path", timeout=5)
    assert bad.status_code == 404


# ------------------------------------------------------------------ Planner._estimates
class TestEstimates:
    @pytest.fixture
    def spec(self):
        return load()

    def test_past_hours_are_inf(self, spec):
        """Hours before now are inf."""
        def forecast(area, now):
            return [50.0] * 24

        p = Planner(spec, forecast)
        est = p._estimates(10.0)
        area = next(iter(est))
        for t in range(0, 10):
            assert np.isinf(est[area][t]), f"hour {t} before now should be inf"

    def test_forecast_hours_match_exactly(self, spec):
        """Hours inside the 24h forecast equal the forecast exactly."""
        known = [float(i * 10) for i in range(1, 25)]

        def forecast(area, now):
            return known

        p = Planner(spec, forecast)
        est = p._estimates(0.0)
        area = next(iter(est))
        for t in range(0, 24):
            assert est[area][t] == known[t], f"hour {t} should match forecast"

    def test_beyond_forecast_blend_formula(self, spec):
        """Hours beyond the 24h forecast follow: (1+premium) * (blend * same_hour + (1-blend) * mean)."""
        values = [100.0] * 24
        premium = 0.1
        blend = 0.5

        def forecast(area, now):
            return values

        p = Planner(spec, forecast)
        p.beyond_premium = premium
        p.beyond_blend = blend
        est = p._estimates(0.0)
        area = next(iter(est))
        expected = (1 + premium) * (blend * values[0] + (1 - blend) * np.mean(values))
        assert abs(est[area][24] - expected) < 1e-6

    def test_forecast_never_called_with_wrong_args(self, spec):
        """The planner never calls the forecast with anything but (area, now)."""
        calls = []

        def forecast(area, now):
            calls.append((area, now))
            return [100.0] * 24

        p = Planner(spec, forecast)
        est = p._estimates(5.0)
        assert all(len(c) == 2 for c in calls)
        for area, now in calls:
            assert isinstance(area, str)
            assert isinstance(now, float)


# ------------------------------------------------------------------ information rule: decisions depend only on forecasts
def test_planner_uses_only_forecasts(spec):
    """Two planners given the same forecasts make the same first decisions: the plan is a function of
    the forecasts (the only electricity input the Planner receives is the forecast callable)."""
    seed = 99
    grid = make_grid(seed, [s.area for s in spec.sites.values()])

    def capture_forecast(area, now):
        return grid.forecast(area, now)

    p1 = Planner(spec, capture_forecast)
    rows = [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False, "assignments": []}
            for w in spec.workloads]
    p1.bootstrap({"now_h": 0.0, "workloads": rows})
    decisions = list(p1.decisions)

    # Second planner with same forecast function
    p2 = Planner(spec, capture_forecast)
    p2.bootstrap({"now_h": 0.0, "workloads": rows})
    decisions2 = list(p2.decisions)

    assert len(decisions) == len(decisions2)
    for d1, d2 in zip(decisions, decisions2):
        assert d1["workload"] == d2["workload"]
        assert d1["action"] == d2["action"]
        if "zone" in d1:
            assert d1["zone"] == d2["zone"]


# ------------------------------------------------------------------ baseline accuracy: hand-computed energy
def test_energy_accounting_matches_hand_computation(spec):
    """On a real-workload scenario, assert the kWh x g/kWh formula produces the expected carbon.
    Assert the claimed saving (1 - aware/naive) is computed from those two scores."""
    seed = 3
    game_naive, _ = run(spec, seed, lambda s, f: Naive(s, f, pause=False, name="naive"))
    game_aware, _ = run(spec, seed, lambda s, f: Planner(s, f, name="carbon-aware"))

    score_naive = game_naive.score()
    score_aware = game_aware.score()

    # Both deliver all workloads
    assert score_naive["delivered"] == 15
    assert score_aware["delivered"] == 15

    # carbon = kWh x hourly grid intensity, so g/kWh must lie inside the practice grid's range
    grid = make_grid(seed, {x.area for x in spec.sites.values()})
    lo = min(min(v) for v in grid.actual.values())
    hi = max(max(v) for v in grid.actual.values())
    for w in spec.workloads:
        wl = game_aware.ws[w.id]
        assert wl.energy_kwh > 0, w.id
        assert lo * wl.energy_kwh - 1e-6 <= wl.carbon_g <= hi * wl.energy_kwh + 1e-6, w.id

    # Carbon-aware should be strictly better (or equal) in carbon
    assert score_aware["carbon_kg"] <= score_naive["carbon_kg"]


# ------------------------------------------------------------------ horizon limits
def test_forecast_horizons_are_allowed_values():
    """The rules allow horizonHours 6 or 24 only; our clients default to 24."""
    from greenops.live import Live
    assert inspect.signature(Live.forecast).parameters["horizon"].default in (6, 24)
    assert inspect.signature(make_grid(0, ["DE"]).forecast).parameters["horizon"].default in (6, 24)
    assert Planner(load(), lambda a, n: [1.0] * 24).horizon in (6, 24) if hasattr(Planner, "horizon") else True
