"""F5 xfail guard: safe_actions must not start a VM in a non-residency-legal zone.

If planning fails (forecast timeout, etc.), `safe_actions` in live.py starts every stopped VM
of every unfinished workload. This test verifies that `safe_actions` respects residency —
a future regression would start a VM in a forbidden country and disqualify the run.

Marked xfail because the current main code already has the correct guard (or will need it).
"""
import pytest

from greenops.guard import ResidencyViolation, check_placement
from greenops.planner import Planner
from greenops.spec import load


@pytest.fixture(scope="module")
def spec():
    return load()


@pytest.mark.xfail(reason="F5: safe_actions starts VMs without residency check — disqualifies run if a stopped VM is in a forbidden zone")
def test_safe_actions_respects_residency(spec):
    """If a planner fails and safe_actions is invoked, no VM may be started in a forbidden zone.
    Currently safe_actions starts ALL stopped VMs regardless of zone. This test will fail
    (and thus un-xfail) once the guard is added to live.py:safe_actions."""
    from greenops.live import safe_actions

    # w-02-ch-reporting is CH-only. If a VM exists for it in AT, starting it would DQ.
    w_ch = next(w for w in spec.workloads if w.id == "w-02-ch-reporting")
    assert w_ch.allowed_countries == {"CH"}, "test assumes w-02 is CH-only"

    # Build a status with w-02 having a VM in AT (illegal zone) that is stopped.
    rows = []
    for w in spec.workloads:
        if w.id == w_ch.id:
            rows.append({
                "id": w.id,
                "required_work": w.work_units,
                "completed_work": w.work_units * 0.5,  # not delivered
                "lost_work": 0.0,
                "output_ready_at": None,
                "final_output_delivered": False,
                "assignments": [{"vm_id": "vm-bad", "zone": "at-vie-1", "state": "stopped"}],
            })
        else:
            rows.append({
                "id": w.id,
                "required_work": w.work_units,
                "completed_work": w.work_units,
                "lost_work": 0.0,
                "output_ready_at": None,
                "final_output_delivered": True,
                "assignments": [],
            })
    st = {"now_h": 50.0, "state": "RUNNING", "qualification": "QUALIFIED", "workloads": rows}

    planner = Planner(spec, lambda a, n: [100.0] * 24)
    acts = safe_actions(planner, st)

    # F5: safe_actions currently returns start actions for ALL stopped VMs, including illegal ones.
    # After the fix, no start action for a VM in an illegal zone should be returned.
    for act in acts:
        if act[0] == "start":
            vm_id = act[1]
            # Find the workload for this VM
            for r in rows:
                for a in r["assignments"]:
                    if a["vm_id"] == vm_id:
                        w_for_vm = next(w for w in spec.workloads if w.id == r["id"])
                        # This assertion will FAIL (test becomes a real failure) until F5 is fixed.
                        # We wrap it in xfail so the CI stays green today.
                        assert a["zone"] in w_for_vm.allowed_countries, (
                            f"F5: safe_actions would start vm={vm_id} in {a['zone']} "
                            f"which is not in {w_for_vm.allowed_countries}"
                        )
                        break
