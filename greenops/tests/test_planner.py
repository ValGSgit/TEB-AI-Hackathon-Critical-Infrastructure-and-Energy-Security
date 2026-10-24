"""The planner on the offline game: legal, on time, and cleaner than the naive baseline."""
import pytest

from greenops import guard
from greenops.model import suitable
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
    # no late crowding: every job lands well before its deadline and none is ever left without a slot
    slack = {w: game.W[w].deadline_h - s.delivered_h for w, s in game.ws.items()}
    assert min(slack.values()) >= 5.0, slack
    assert not [d for d in planner.decisions if d["action"] == "blocked"]
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


def _legal_zone(spec, w):
    return next(z.id for z in spec.zones if guard.is_allowed(w, z)
                and any(p.available_in(z.id) and suitable(p, w) for p in spec.profiles))


def test_deletes_only_after_delivery(spec):
    p = Planner(spec, lambda a, n: [100.0] * 24)
    rows = [{"id": w.id, "required_work": w.work_units, "completed_work": w.work_units / 2, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": w.id == "w-01-dach-research",
             "assignments": [{"vm_id": f"vm-{w.id}", "zone": _legal_zone(spec, w), "state": "running"}]}
            for w in spec.workloads]
    acts = p.decide({"now_h": 50.0, "workloads": rows})
    deletes = [a for a in acts if a[0] == "delete"]
    assert deletes == [("delete", "vm-w-01-dach-research", "w-01-dach-research")]


def test_adopts_vms_it_did_not_create(spec):
    """After a controller restart the planner continues with the VMs it finds, using their known profile."""
    w = next(w for w in spec.workloads if w.kind == "cpu")
    zone = _legal_zone(spec, w)
    known = next(pr.id for pr in spec.profiles if pr.available_in(zone) and suitable(pr, w))
    p = Planner(spec, lambda a, n: [100.0] * 24)
    p.vm_profile["vm-a"] = known
    rows = [{"id": x.id, "required_work": x.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False,
             "assignments": ([{"vm_id": "vm-a", "zone": zone, "state": "running"},
                              {"vm_id": "vm-b", "zone": zone, "state": "stopped"}] if x.id == w.id else [])}
            for x in spec.workloads]
    p.decide({"now_h": max(w.release_h, 1.0), "workloads": rows})
    assert p.placements[w.id].zone_id == zone and p.placements[w.id].profile_id == known
    assert p.placements[w.id].workers == 2
    assert any(d["action"] == "adopt" and d["workload"] == w.id for d in p.decisions)


def _fresh_rows(spec):
    return [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False, "assignments": []} for w in spec.workloads]


@pytest.mark.parametrize("commit_h", [2, -1])
def test_close_start_is_kept_when_later_hours_look_cleaner(spec, commit_h):
    """A start planned within commit_h hours is not pushed later by the next forecast (-1: it is)."""
    fc = {"f": [100.0] * 24}
    p = Planner(spec, lambda a, n: fc["f"], commit_h=commit_h)
    rows = {r["id"]: r for r in _fresh_rows(spec)}
    p._replan(rows, 0.0)
    wid, slot = min(((w, s) for w, s in p.plan.items() if s.start >= 3), key=lambda kv: kv[1].start)
    fc["f"] = [1000.0] * 6 + [10.0] * 18          # the next hours turn dirty, later ones clean
    p._replan(rows, float(slot.start - 2))
    if commit_h >= 0:
        assert p.plan[wid].start == slot.start and p.plan[wid].commit
        assert p.plan[wid].placement == slot.placement
    else:
        assert p.plan[wid].start > slot.start
