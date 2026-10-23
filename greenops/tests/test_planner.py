"""The planner on the offline game: legal, on time, and cleaner than the naive baseline."""
import pytest

from greenops import guard
from greenops.play import Naive, run
from greenops.planner import Planner
from greenops.spec import load


@pytest.fixture(scope="module")
def spec():
    return load()


@pytest.mark.parametrize("seed", [11, 12])
def test_full_run_is_legal_on_time_and_cleaner(spec, seed, monkeypatch):
    seen = []
    real = guard.check_placement

    def spy(w, z):
        seen.append((w.id, z.id))
        return real(w, z)

    monkeypatch.setattr("greenops.planner.check_placement", spy)
    game, planner = run(spec, seed, lambda s, f: Planner(s, f))
    score = game.score()
    assert not game.disqualified
    assert score["delivered"] == 15 and score["all_done"]
    assert not game.vms, "every VM is deleted after delivery"
    assert seen and all(z.split("-")[0].upper() in game.W[w].allowed_countries for w, z in seen)
    base, _ = run(spec, seed, lambda s, f: Naive(s, f, pause=False, name="naive"))
    assert game.score()["carbon_kg"] < 0.8 * base.score()["carbon_kg"]


def test_forecast_is_the_only_electricity_input(spec):
    """The planner never asks for more than 24 forecast hours and never sees actuals."""
    calls = []

    def forecast(area, now):
        calls.append((area, now))
        return [100.0] * 24

    p = Planner(spec, forecast)
    rows = [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False, "assignments": []} for w in spec.workloads]
    acts = p.bootstrap({"now_h": 0.0, "workloads": rows})
    assert calls and len(acts) >= 1 and acts[0][0] == "create"


def test_deletes_only_after_delivery(spec):
    p = Planner(spec, lambda a, n: [100.0] * 24)
    rows = [{"id": w.id, "required_work": w.work_units, "completed_work": w.work_units / 2, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": w.id == "w-01-dach-research",
             "assignments": [{"vm_id": f"vm-{w.id}", "zone": "de-fra-1", "state": "running"}]} for w in spec.workloads]
    acts = p.decide({"now_h": 50.0, "workloads": rows})
    deletes = [a for a in acts if a[0] == "delete"]
    assert deletes == [("delete", "vm-w-01-dach-research", "w-01-dach-research")]
