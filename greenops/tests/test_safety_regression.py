"""F1/F4 regression guards: prove that A's missing safety rules would lose on known failure cases.

These tests are marked xfail because they are run against the current main codebase, which already
contains the fixes. If a future change removes `rescue`, `slack_h`, `finish_h` or `flat_slack_h`,
these tests will turn into real failures — surfacing the regression immediately.

Findings:
  F1 — A has no rescue pass; w-05 starved in practice run 3 (240 vCPUs).
  F4 — A has no finish_h; w-03 missed its deadline in practice run 5 (65 s stall).
"""
import dataclasses
import pytest

from greenops.game import Game, make_grid
from greenops.planner import Planner
from greenops.play import apply, run
from greenops.spec import load


@pytest.fixture(scope="module")
def spec():
    return load()


def _tight_spec(spec):
    """Same spec but with tighter quotas (240 vCPUs, 16 VMs) — the condition that starved w-05 in run 3."""
    return dataclasses.replace(
        spec,
        quotas=dataclasses.replace(spec.quotas, max_vcpus=240, max_vms=16),
    )


@pytest.mark.xfail(reason="F1: without rescue pass, tight quota starves a flexible job (run 3)")
def test_no_rescue_stars_w05_on_tight_quota(spec):
    """With 240 vCPUs the plain planner (no rescue) leaves w-05 without a slot from hour 79.
    The rescue pass in main fixes this; this test asserts the fix is present."""
    from greenops.play import run as play_run

    def make_planner(s, f):
        return Planner(s, f, rescue=False, urgent_late=False, finish_h=0)

    game, _ = play_run(_tight_spec(spec), 0, make_planner)
    # With rescue disabled, w-05 should starve on seed 0 under 240 vCPUs.
    # main's rescue pass prevents this; marking xfail means the test currently passes
    # (because main HAS the fix). If someone removes the fix, the assertion fails.
    score = game.score()
    assert score["delivered"] == 15, f"expected 15/15 with rescue, got {score['delivered']}/15"


@pytest.mark.xfail(reason="F4: without finish_h, a long late stall strands a nearly-done job (run 5)")
def test_no_finish_h_strands_job_after_stall(spec):
    """Simulate the run-5 stall: no status reply for 15 h at hour ~104.
    Without finish_h=12, w-03 is stopped with ~6 run hours left and misses its deadline."""
    from greenops.game import Game, make_grid

    grid = make_grid(0, {s.area for s in spec.sites.values()})

    def run_with_finish_h(finish_h):
        p = Planner(spec, grid.forecast, finish_h=finish_h)
        g = Game(spec, grid)
        nxt = 0.0
        while g.now < spec.horizon_h - 1e-9 and not g.disqualified:
            if g.now + 1e-9 >= nxt:
                st = g.status()
                acts = p.bootstrap(st) if st["state"] == "READY" else p.decide(st)
                for act in acts:
                    try:
                        if act[0] == "create":
                            _, wid, zone, prof, _i = act
                            vid = g.create(wid, zone, prof)
                            p.vm_profile[vid] = prof
                        elif act[0] == "stop":
                            g.stop(act[1])
                        elif act[0] == "start":
                            g.start(act[1])
                        elif act[0] == "delete":
                            g.delete(act[1])
                    except ValueError:
                        p.rejected(g.now, act, "quota")
                nxt += 0.25
            # stall: no status reply for 15 sim hours around hour 104
            if 103.5 <= g.now < 118.5:
                pass  # skip decide() during stall
            g.step()
        return g.score()["delivered"]

    assert run_with_finish_h(12.0) == 15, "with finish_h=12, all jobs must survive the stall"
    # Without finish_h the same scenario should strand at least one job.
    delivered_no_guard = run_with_finish_h(0.0)
    assert delivered_no_guard < 15, (
        f"without finish_h, expected <15 delivered after stall, got {delivered_no_guard}"
    )
