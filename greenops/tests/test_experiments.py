from greenops import catalog as C
from greenops.experiments import run
from greenops.scenario import make_scenario


def test_ladder_runs_and_never_disqualifies():
    d = run(2)
    keys = [r["key"] for r in d["rungs"]]
    assert keys == ["baseline", "zone", "wait", "no-cleanup"]
    assert all(r["disqualified"] == 0 for r in d["rungs"])
    by = {r["key"]: r for r in d["rungs"]}
    assert by["wait"]["carbon_mean"] < by["baseline"]["carbon_mean"]
    assert by["no-cleanup"]["energy_mean"] > by["wait"]["energy_mean"]     # idle VMs cost energy


def test_scenarios_match_the_known_challenge_shape():
    sc = make_scenario(0)
    assert [w.id for w in sc.workloads] == [w[0] for w in C.WORKLOADS]
    assert {z.country for z in sc.zones} == {"AT", "BG", "CH", "DE", "ES", "FR", "HR", "IT"} and len(sc.zones) == 11
    assert sc.quotas.max_vms == 20 and sc.quotas.max_vcpus == 320 and sc.quotas.gpu_caps["RTX6000Pro"] == 4
    for wid, _n, kind, countries in C.WORKLOADS:
        w = next(x for x in sc.workloads if x.id == wid)
        assert w.kind == kind and w.allowed_countries == frozenset(countries)
