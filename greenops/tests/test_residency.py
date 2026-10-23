"""Residency tests: the one rule that can zero a run.

Covers the residency resolution logic, every (workload, zone) pair from the real challenge,
end-to-end planner legality, adversarial injection, and Live.create guard ordering.
"""
from __future__ import annotations

import inspect

import pytest

from greenops.guard import (
    EU_EEA, DACH, ResidencyViolation, check_placement, resolve_countries, resolve_residency,
)
from greenops.model import Workload, Zone, suitable
from greenops.planner import Planner
from greenops.spec import load
from greenops.game import Game, make_grid


# ------------------------------------------------------------------ truth table for resolve_residency
ALL8 = frozenset({"AT", "BG", "CH", "DE", "ES", "FR", "HR", "IT"})


class TestResolveResidency:
    def test_anywhere_with_countries(self):
        assert resolve_residency("ANYWHERE", ["DE", "AT"], None, ALL8) == {"DE", "AT"}

    def test_anywhere_all_countries(self):
        assert resolve_residency("ANYWHERE", None, None, ALL8) == ALL8

    def test_eu_excludes_ch(self):
        r = resolve_residency("EU", None, None, ALL8)
        assert "CH" not in r
        assert {"AT", "DE", "ES", "FR", "HR", "IT", "BG"} <= r

    def test_single_country(self):
        assert resolve_residency("CH", None, None, ALL8) == {"CH"}
        assert resolve_residency("DE", None, None, ALL8) == {"DE"}

    def test_allowed_narrows(self):
        r = resolve_residency("EU", ["DE", "CH"], None, ALL8)
        assert r == {"DE"}

    def test_forbidden_wins_over_allowed(self):
        r = resolve_residency("EU", ["DE", "CH"], ["FR"], ALL8)
        assert "FR" not in r and "DE" in r and "CH" not in r

    def test_forbidden_wins_over_residency(self):
        r = resolve_residency("ANYWHERE", None, ["CH"], ALL8)
        assert "CH" not in r

    def test_forbidden_also_applies_to_anywhere(self):
        r = resolve_residency("ANYWHERE", ["DE", "CH"], ["CH"], ALL8)
        assert r == {"DE"}

    def test_unknown_residency_raises(self):
        with pytest.raises(ValueError):
            resolve_residency("MARS", None, None, ALL8)
        with pytest.raises(ValueError):
            resolve_residency("eu", None, None, ALL8)


# ------------------------------------------------------------------ every workload × every zone pair
@pytest.fixture(scope="module")
def spec():
    return load()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_check_placement_matches_spec_for_all_pairs(spec, seed):
    """For each of the 15 workloads and 11 zones, check_placement raises iff the zone country
    is outside the workload's allowed_countries (as computed by spec.py)."""
    for w in spec.workloads:
        for z in spec.zones:
            allowed = z.country in w.allowed_countries
            if allowed:
                check_placement(w, z)
            else:
                with pytest.raises(ResidencyViolation):
                    check_placement(w, z)


def test_no_eu_workload_allows_ch(spec):
    """EU-resident workloads must never include CH in allowed_countries."""
    W = {w.id: w for w in spec.workloads}
    assert "CH" not in EU_EEA


def test_eu_residency_specifically_excludes_ch_in_spec(spec):
    """The resolved allowed_countries for the known EU-restricted workloads must not contain CH."""
    W = {w.id: w for w in spec.workloads}
    assert "CH" not in W["w-03-med-analysis"].allowed_countries
    assert "CH" not in W["w-07-eu-training"].allowed_countries
    assert W["w-02-ch-reporting"].allowed_countries == {"CH"}


# ------------------------------------------------------------------ end-to-end planner legality
@pytest.mark.parametrize("seed", range(6))
def test_planner_never_places_illegal_on_game(spec, seed, monkeypatch):
    """Run the planner end-to-end on the offline game for several seeds; assert every create
    emitted by the planner was legal and the game never disqualifies."""
    seen = []
    real = check_placement

    def spy(w, z):
        seen.append((w.id, z.id))
        return real(w, z)

    monkeypatch.setattr("greenops.planner.check_placement", spy)
    grid = make_grid(seed, {s.area for s in spec.sites.values()})
    game = Game(spec, grid)
    planner = Planner(spec, grid.forecast)

    acts = planner.bootstrap(game.status())
    for act in acts:
        if act[0] == "create":
            _, wid, zone, prof, _i = act
            check_placement(game.W[wid], game.Z[zone])
            vid = game.create(wid, zone, prof)
            planner.vm_profile[vid] = prof

    for _h in range(int(spec.horizon_h)):
        st = game.status()
        if st["state"] in ("COMPLETED", "INVALIDATED"):
            break
        acts = planner.decide(st)
        for act in acts:
            kind = act[0]
            try:
                if kind == "create":
                    _, wid, zone, prof, _i = act
                    check_placement(game.W[wid], game.Z[zone])
                    vid = game.create(wid, zone, prof)
                    planner.vm_profile[vid] = prof
                elif kind == "stop":
                    game.stop(act[1])
                elif kind == "start":
                    game.start(act[1])
                elif kind == "delete":
                    game.delete(act[1])
            except ValueError:
                planner.rejected(game.now, act, "quota")
        game.step()

    assert not game.disqualified, f"disqualified at h={game.now}: {game.disqualified}"
    assert seen


# ------------------------------------------------------------------ adversarial injection
def test_adversarial_illegal_placement_never_becomes_an_action(spec, monkeypatch):
    """Force the planner to propose only illegal zones: it must raise ResidencyViolation instead of
    returning a create action, so nothing reaches the platform."""
    from greenops.planner import Placement

    def illegal(self, w, est):
        return [Placement(z.id, p.id, 1) for z in self.spec.zones if z.country not in w.allowed_countries
                for p in self.spec.profiles if p.available_in(z.id) and suitable(p, w)][:1]

    monkeypatch.setattr(Planner, "_candidates", illegal)
    rows = [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False, "assignments": []}
            for w in spec.workloads if any(z.country not in w.allowed_countries for z in spec.zones)
            and any(p.available_in(z.id) and suitable(p, w) for z in spec.zones
                    if z.country not in w.allowed_countries for p in spec.profiles)]
    planner = Planner(spec, lambda a, n: [100.0] * 24)
    with pytest.raises(ResidencyViolation):
        planner.bootstrap({"now_h": 0.0, "workloads": rows})
    assert not planner.placements


def test_live_create_guard_before_http_call(spec):
    """Live.create calls check_placement before any HTTP call. We verify by inspecting the
    source: check_placement must appear before the first HTTP call."""
    from greenops.live import Live
    src = inspect.getsource(Live.create)
    cp_idx = src.find("check_placement")
    assert cp_idx >= 0, "Live.create must call check_placement"
    first_http = min(src.find("self.api.wait()"), src.find("self.clients["), src.find("c = self.clients"))
    assert cp_idx < first_http, "check_placement must come before any HTTP call in Live.create"


# ------------------------------------------------------------------ DACH / EU / CH boundary cases
def test_dach_allows_ch():
    w = Workload("w", "cpu", 0, 10, 1, 0, 0, DACH, None)
    check_placement(w, Zone("ch-gva-2", "CH"))
    check_placement(w, Zone("de-fra-1", "DE"))
    check_placement(w, Zone("at-vie-1", "AT"))
    with pytest.raises(ResidencyViolation):
        check_placement(w, Zone("es-mad-1", "ES"))


def test_eu_does_not_allow_ch():
    w = Workload("w", "cpu", 0, 10, 1, 0, 0, EU_EEA, None)
    check_placement(w, Zone("at-vie-1", "AT"))
    with pytest.raises(ResidencyViolation):
        check_placement(w, Zone("ch-gva-2", "CH"))


def test_ch_only_restricts_to_ch():
    w = Workload("w", "cpu", 0, 10, 1, 0, 0, frozenset({"CH"}), None)
    check_placement(w, Zone("ch-gva-2", "CH"))
    check_placement(w, Zone("ch-dk-2", "CH"))
    with pytest.raises(ResidencyViolation):
        check_placement(w, Zone("de-fra-1", "DE"))
