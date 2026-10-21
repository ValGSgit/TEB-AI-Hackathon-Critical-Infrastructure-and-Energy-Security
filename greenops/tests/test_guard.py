"""The one rule that can zero a run: never place a workload in a forbidden country."""
import pytest

from greenops.controller import run_sim
from greenops.guard import DACH, ResidencyViolation, check_placement, resolve_countries
from greenops.policy import Baseline, CarbonAware, Context, options_for
from greenops.scenario import ALL_COUNTRIES, make_scenario
from greenops.model import Workload, Zone


def wl(countries):
    return Workload("t", "cpu", 0, 10, 1, 0, 0, frozenset(countries), None)


def test_eu_residency_excludes_switzerland():
    eu = resolve_countries(eu_residency=True, all_countries=ALL_COUNTRIES)
    assert "CH" not in eu and "AT" in eu and "DE" in eu


def test_explicit_list_still_applies_with_eu_flag():
    assert resolve_countries(eu_residency=True, countries={"CH", "AT"}) == frozenset({"AT"})


def test_guard_blocks_forbidden_country():
    with pytest.raises(ResidencyViolation):
        check_placement(wl({"CH"}), Zone("at-vie-1", "AT"))
    check_placement(wl(DACH), Zone("at-vie-1", "AT"))


def test_empty_allow_list_blocks_everything():
    with pytest.raises(ResidencyViolation):
        check_placement(wl(set()), Zone("ch-gva-2", "CH"))


@pytest.mark.parametrize("seed", range(6))
def test_options_are_always_legal(seed):
    sc = make_scenario(seed)
    ctx = Context(sc.zones, sc.profiles, sc.workloads, sc.quotas, sc.boot_h, sc.carbon.forecast)
    for w in sc.workloads:
        for o in options_for(ctx, w.id, w.work_units):
            assert ctx.Z[o.zone_id].country in w.allowed_countries


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("policy", [Baseline, CarbonAware])
def test_full_runs_never_disqualified(seed, policy):
    r = run_sim(make_scenario(seed), policy())
    assert "disqualified" not in r


def test_carbon_aware_beats_baseline_on_average():
    a = b = 0
    for seed in range(6):
        sc = make_scenario(seed)
        a += run_sim(sc, CarbonAware())["carbon_kg"]
        b += run_sim(sc, Baseline())["carbon_kg"]
    assert a < b
