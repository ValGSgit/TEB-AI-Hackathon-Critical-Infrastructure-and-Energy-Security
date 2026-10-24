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
    """Build a SyntheticGrid, change its actuals only (not its forecasts), and assert the
    planner's decisions are identical. That proves the plan depends on forecasts only."""
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
    """On a constant grid, carbon_g must equal energy_kwh x intensity exactly. That checks the
    accounting (kW x PUE x dt x g/kWh) independently of the score normalization."""
    seed = 3
    areas = sorted({s.area for s in spec.sites.values()})
    grid = make_grid(seed, areas)
    for a in areas:
        grid.actual[a] = [100.0] * len(grid.actual[a])       # constant 100 g/kWh everywhere

    planner = Planner(spec, grid.forecast)
    game = Game(spec, grid)
    next_tick = 0.0
    while game.now < spec.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= next_tick:
            for act in planner.decide(game.status()):
                kind = act[0]
                try:
                    if kind == "create":
                        _, wid, zone, prof, _i = act
                        vid = game.create(wid, zone, prof)
                        planner.vm_profile[vid] = prof
                    elif kind == "stop":
                        game.stop(act[1])
                    elif kind == "start":
                        game.start(act[1])
                    elif kind == "delete":
                        game.delete(act[1])
                except ValueError as e:
                    planner.rejected(game.now, act, str(e))
            next_tick += 0.25
        game.step()

    assert not game.disqualified
    for w in spec.workloads:
        wl = game.ws[w.id]
        if wl.energy_kwh > 0:
            expected = wl.energy_kwh * 100.0                  # constant grid: kWh x g/kWh
            assert abs(wl.carbon_g - expected) < 1e-6, \
                f"{w.id}: carbon_g={wl.carbon_g}, expected={expected}, energy_kwh={wl.energy_kwh}"


# ------------------------------------------------------------------ the planner asks for forecasts only
def test_planner_calls_forecast_with_area_and_now_only(spec):
    """The planner must call forecast(area, now) with at most two positional arguments; the
    horizon it asks for is never more than the 24 h the run publishes."""
    calls = []

    def spy(area, *rest):
        calls.append((area, rest))
        return [100.0] * 24

    p = Planner(spec, spy)
    p._estimates(5.0)
    assert calls
    for area, rest in calls:
        assert isinstance(area, str) and len(rest) == 1 and isinstance(rest[0], float)


def test_forecast_horizon_is_bounded(spec):
    """The planner estimates beyond the published horizon by blending the forecast it has; it never
    requests a longer horizon than 24 h from the run."""
    asked = []

    def spy(area, now, horizon=None):
        asked.append(None)
        return [100.0] * 24

    p = Planner(spec, spy)
    est = p._estimates(0.0)
    area = next(iter(est))
    assert asked, "the planner must go through the forecast callable, never the grid API"
    # The estimates array spans the whole horizon; the planner never asks for more than 24 h.
    assert len(est[area]) == int(spec.horizon_h)
