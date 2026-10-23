"""The vendored challenge files load, match their hashes, and resolve residency correctly."""
import pytest

from greenops.guard import EU_EEA, ResidencyViolation, check_placement, resolve_residency
from greenops.spec import load


@pytest.fixture(scope="module")
def spec():
    return load()


def test_counts_and_quotas(spec):
    assert len(spec.workloads) == 15 and len(spec.zones) == 11 and len(spec.profiles) == 22
    assert (spec.quotas.max_vms, spec.quotas.max_vcpus) == (20, 320)
    assert spec.quotas.gpu_caps["gpurtx6000pro"] == 4
    assert sum(w.work_units for w in spec.workloads if w.kind == "cpu") == 14600


def test_residency_resolution():
    all8 = {"AT", "BG", "CH", "DE", "ES", "FR", "HR", "IT"}
    assert resolve_residency("EU", None, None, all8) == all8 - {"CH"}          # Switzerland is outside EU
    assert resolve_residency("ANYWHERE", ["DE", "AT", "CH"], ["FR"], all8) == {"DE", "AT", "CH"}
    assert resolve_residency("CH", None, ["FR"], all8) == {"CH"}
    assert resolve_residency("EU", ["DE", "CH"], None, all8) == {"DE"}           # allow list cannot add CH to EU
    assert resolve_residency("EU", None, ["FR"], all8) == all8 - {"CH", "FR"}
    with pytest.raises(ValueError):
        resolve_residency("MARS", None, None, all8)


def test_each_workload_has_legal_zones_only(spec):
    W = {w.id: w for w in spec.workloads}
    assert W["w-02-ch-reporting"].allowed_countries == {"CH"}
    assert W["w-03-med-analysis"].allowed_countries == {"ES", "IT"}
    assert "FR" not in W["w-01-dach-research"].allowed_countries
    for w in spec.workloads:
        assert w.allowed_countries, w.id
        if "CH" in w.allowed_countries and w.id not in ("w-02-ch-reporting", "w-08-ch-imaging"):
            assert w.allowed_countries <= {"DE", "AT", "CH"}       # only the DACH 'ANYWHERE' jobs may use CH


def test_guard_blocks_every_illegal_pair(spec):
    for w in spec.workloads:
        for z in spec.zones:
            if z.country in w.allowed_countries:
                check_placement(w, z)
            else:
                with pytest.raises(ResidencyViolation):
                    check_placement(w, z)


def test_units(spec):
    P = {p.id: p for p in spec.profiles}
    mega = P["20000000-0000-4000-8000-000000000003"]
    assert mega.cpu_throughput == 32 and abs(mega.power_kw - 0.0926758) < 1e-6
    rtx = P["20000000-0000-4000-8000-000000000020"]
    assert rtx.gpu_throughput == 800 * 3600 and rtx.zones == {"de-fra-1", "hr-zag-1", "ch-dk-2"}
    assert spec.rules["reference_g_per_kwh"] == 200 and spec.rules["local_weight"] == 0.75


def test_timestamps_with_any_fraction_length():
    """The real work status sends fractions of 2 or 3 digits; Python < 3.11 rejects the 2-digit form."""
    from greenops.spec import to_h
    assert to_h("2025-09-30T00:00:00Z") == 0.0
    assert abs(to_h("2025-10-02T20:27:40.91+00:00") - (68 + 27 / 60 + 40.91 / 3600)) < 1e-9
    assert abs(to_h("2025-10-02T20:05:10.904Z") - (68 + 5 / 60 + 10.904 / 3600)) < 1e-9
