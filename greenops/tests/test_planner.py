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


@pytest.mark.parametrize("seed", [0, 3])
def test_no_job_starves_when_quota_is_tight(spec, seed):
    """Run 3 left w-05 without a slot from hour 65 to the end. With 240 vCPUs instead of 320 the same starvation
    happens offline without the rescue pass; with it, every job is still delivered on time."""
    import dataclasses
    tight = dataclasses.replace(spec, quotas=dataclasses.replace(spec.quotas, max_vcpus=240, max_vms=16))
    game, _ = run(tight, seed, lambda s, f: Planner(s, f))
    assert game.score()["delivered"] == 15 and not game.disqualified
    old, _ = run(tight, seed, lambda s, f: Planner(s, f, rescue=False, urgent_late=False, finish_h=0, flat_slack_h=0))
    assert old.score()["delivered"] < 15, "the stress case must still reproduce the starvation"


def test_planning_never_crashes_near_the_end_of_the_run(spec):
    """A created job whose remaining work runs past hour 120 used to index past the cost array (IndexError),
    which in a live run would fail every poll. It must fall back to running every hour instead."""
    w = next(x for x in spec.workloads if x.id == "w-03-med-analysis")
    zone = _legal_zone(spec, w)
    p = Planner(spec, lambda a, n: [100.0] * 24)
    p.vm_profile["vm-a"] = next(pr.id for pr in spec.profiles if pr.available_in(zone) and suitable(pr, w))
    rows = [{"id": x.id, "required_work": x.work_units, "completed_work": 0.0 if x.id == w.id else x.work_units,
             "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": x.id != w.id,
             "assignments": [{"vm_id": "vm-a", "zone": zone, "state": "stopped"}] if x.id == w.id else []}
            for x in spec.workloads]
    acts = p.decide({"now_h": 110.0, "workloads": rows})
    assert ("start", "vm-a", w.id) in acts and p.plan[w.id].run == frozenset(range(110, p.plan[w.id].end))


def test_a_long_platform_stall_does_not_strand_a_nearly_done_job(spec):
    """Run 5: a 65 s status reply (about 13 simulated hours at 720x) left w-03 stopped with 6 run hours to go,
    and it missed its deadline. Jobs with at most finish_h run hours left now run without pauses."""
    from greenops.game import Game, make_grid
    from greenops.play import apply

    def stalled(**kw):
        grid = make_grid(0, {s.area for s in spec.sites.values()})
        p, g, nxt = Planner(spec, grid.forecast, **kw), Game(spec, grid), 0.0
        while g.now < spec.horizon_h - 1e-9:
            if g.now + 1e-9 >= nxt:
                if not 103.5 <= g.now < 118.5:          # no status reply for 15 simulated hours
                    apply(g, p, p.decide(g.status()))
                nxt += 3.0                              # and one reply every 3 hours, as in run 5
            g.step()
        return g.score()["delivered"]

    assert stalled() == 15
    assert stalled(finish_h=0, flat_slack_h=0) < 15, "the stall must still strand a job without the rules"


def test_a_slow_platform_makes_created_jobs_pause_less(spec):
    """The pause threshold grows with the longest gap between status replies (gap_factor x gap_h)."""
    p = Planner(spec, lambda a, n: [100.0] * 24)
    assert p._flat_slack() == p.flat_slack_h
    p.gap_h = 9.0
    assert p._flat_slack() == max(p.flat_slack_h, p.gap_factor * 9.0) > p.flat_slack_h


def test_planner_profiles(spec):
    """GREENOPS_PLANNER picks a named configuration; the default is the judged one, unknown names fail fast."""
    from greenops.planner import PROFILES, make_planner
    d, r2 = make_planner(spec, lambda a, n: [100.0] * 24), make_planner(spec, lambda a, n: [100.0] * 24, "run2plus")
    assert (d.slack_h, d.finish_h, d.rescue) == (Planner.slack_h, Planner.finish_h, True)
    assert (r2.slack_h, r2.commit_h, r2.finish_h, r2.flat_slack_h, r2.gap_factor) == (0, -1, 0, 0, 0)
    assert r2.rescue and r2.urgent_late, "run2plus keeps the zero-cost protections"
    with pytest.raises(ValueError):
        make_planner(spec, lambda a, n: [100.0] * 24, "nope")
    assert set(PROFILES) == {"default", "run2plus"}
