"""The run analysis reads only the run's own logs and says where every delivery time came from."""
import json

import pytest

from greenops.analyze import analyze
from greenops.spec import load, to_ts


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n{torn", encoding="utf-8")


def _healthy_rows(spec):
    W = {w.id: w for w in spec.workloads}
    return [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0, "lost_work": 0.0,
             "output_ready_at": None, "final_output_delivered": False, "assignments": []}
            for w in spec.workloads]


def test_slack_drift_and_sources(tmp_path):
    spec = load()
    a, b = spec.workloads[0], spec.workloads[1]
    row = lambda w, done, at=None: {"id": w.id, "final_output_delivered": done, "assignments": [],
                                    **({"succeeded_at": to_ts(at)} if at is not None else {})}
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r1", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [row(a, False), row(b, False)]},
        {"run_id": "r1", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [row(a, True, a.deadline_h - 3), row(b, False)]}])
    _write(tmp_path / "decisions.jsonl", [
        {"t": 1.0, "workload": a.id, "action": "wait", "reason": "planned start at hour 7: cleaner"},
        {"t": 9.0, "workload": a.id, "action": "create", "zone": "z", "workers": 1, "block": [9, 20]},
        {"t": 30.0, "workload": b.id, "action": "blocked", "reason": "no quota"},
        {"t": b.deadline_h - 1, "workload": b.id, "action": "delete", "reason": "final output delivered"}])
    (tmp_path / "console.log").write_text('{"end": "all delivered and cleaned up", "t": 117.0}\n', encoding="utf-8")
    run = analyze(tmp_path, spec)
    ra, rb = run["workloads"][a.id], run["workloads"][b.id]
    assert ra["slack_h"] == 3.0 and ra["source_delivered"].startswith("status.jsonl:2")
    assert rb["slack_h"] == 1.0 and "upper bound" in rb["source_delivered"]
    assert run["summary"]["created_later_than_first_plan_h"] == {a.id: 2.0}
    assert run["summary"]["blocked"] == 1 and run["end"]["source"] == "console.log:1"
    assert run["run_id"] == "r1" and run["qualification"] == "QUALIFIED"


def test_restart_keeps_first_create_and_counts_adopts(tmp_path):
    """A controller restart produces an 'adopt' decision; a subsequent identical 'create' must not
    overwrite created_h. restarts == number of adopt lines."""
    spec = load()
    w = spec.workloads[0]
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r2", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [{"id": w.id, "required_work": w.work_units, "completed_work": w.work_units * 0.3,
                        "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": False,
                        "assignments": [{"vm_id": "vm-x", "zone": "at-vie-1", "state": "running"}]}]}])
    _write(tmp_path / "decisions.jsonl", [
        {"t": 10.0, "workload": w.id, "action": "adopt", "reason": "existing VMs found", "zone": "at-vie-1", "profile": "p1"},
        {"t": 10.0, "workload": w.id, "action": "create", "zone": "at-vie-1", "profile": "p1", "workers": 1, "block": [10, 30]},
        {"t": 11.0, "workload": w.id, "action": "create", "zone": "at-vie-1", "profile": "p1", "workers": 1, "block": [10, 30]},
        {"t": 50.0, "workload": w.id, "action": "delete", "reason": "final output delivered"}])
    (tmp_path / "console.log").write_text('{"end": "all delivered and cleaned up", "t": 55.0}\n')
    run = analyze(tmp_path, spec)
    rw = run["workloads"][w.id]
    assert rw["created_h"] == 10.0, "created_h must stay at the first create, not the post-restart one"
    assert run["restarts"] == 1, "one adopt line => one restart"
    assert rw["zone"] == "at-vie-1" and rw["workers"] == 1


def test_torn_lines_are_skipped(tmp_path):
    """A torn last line in both status.jsonl and decisions.jsonl must be skipped, not crash."""
    spec = load()
    w = spec.workloads[0]
    # Write a valid line then a torn one
    valid = {"run_id": "r3", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
             "workloads": [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0,
                            "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": False,
                            "assignments": []}]}
    path = tmp_path / "status.jsonl"
    path.write_text(json.dumps(valid) + "\n{torn", encoding="utf-8")
    dec = tmp_path / "decisions.jsonl"
    dec.write_text('{"t": 1.0, "workload": "' + w.id + '", "action": "wait"}\n{"torn', encoding="utf-8")
    # Should not raise
    run = analyze(tmp_path, spec)
    assert run["samples"] == 1
    assert run["run_id"] == "r3"


def test_undelivered_workload_has_none_slack(tmp_path):
    """A workload that is never delivered gets slack_h=None; summary.on_time counts only delivered jobs."""
    spec = load()
    a, b = spec.workloads[0], spec.workloads[1]
    row = lambda w, delivered, delivered_at=None: {
        "id": w.id, "required_work": w.work_units, "completed_work": w.work_units if delivered else w.work_units * 0.5,
        "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": delivered,
        "assignments": [],
        **({"succeeded_at": to_ts(delivered_at)} if delivered_at is not None else {})}
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r4", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [row(a, True, a.deadline_h - 2), row(b, False)]}])
    _write(tmp_path / "decisions.jsonl", [
        {"t": 5.0, "workload": a.id, "action": "create", "zone": "at-vie-1", "workers": 1, "block": [5, 20]},
        {"t": 5.0, "workload": b.id, "action": "create", "zone": "at-vie-1", "workers": 1, "block": [5, 30]},
        {"t": 40.0, "workload": a.id, "action": "delete", "reason": "final output delivered"}])
    (tmp_path / "console.log").write_text('{"end": "all delivered and cleaned up", "t": 119.0}\n')
    run = analyze(tmp_path, spec)
    assert run["workloads"][a.id]["slack_h"] == 2.0
    assert run["workloads"][b.id]["slack_h"] is None
    assert run["summary"]["on_time"] == 1
    assert run["summary"]["delivered"] == 1


def test_no_console_log_means_no_end(tmp_path):
    """When console.log is absent, run['end'] is None."""
    spec = load()
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r5", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [{"id": w.id, "required_work": w.work_units, "completed_work": 0.0,
                        "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": False,
                        "assignments": []} for w in spec.workloads]}])
    # No decisions.jsonl, no console.log
    run = analyze(tmp_path, spec)
    assert run["end"] is None


def test_blocked_then_created_both_reported(tmp_path):
    """A job that is first 'blocked' and later 'create'd: both events appear in the per-job log."""
    spec = load()
    w = spec.workloads[0]
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r6", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [{"id": w.id, "required_work": w.work_units, "completed_work": w.work_units,
                        "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": True,
                        "assignments": [], "succeeded_at": to_ts(w.deadline_h - 3)}]}])
    _write(tmp_path / "decisions.jsonl", [
        {"t": 5.0, "workload": w.id, "action": "blocked", "reason": "no quota"},
        {"t": 10.0, "workload": w.id, "action": "create", "zone": "at-vie-1", "profile": "p1",
         "workers": 1, "block": [10, 30]},
        {"t": 40.0, "workload": w.id, "action": "delete", "reason": "final output delivered"}])
    (tmp_path / "console.log").write_text('{"end": "all delivered and cleaned up", "t": 45.0}\n')
    run = analyze(tmp_path, spec)
    rw = run["workloads"][w.id]
    assert len(rw["blocked"]) == 1 and "t=5.0" in rw["blocked"][0]
    assert rw["created_h"] == 10.0
    assert rw["slack_h"] == 3.0


def test_rejected_delete_is_listed(tmp_path):
    """A 'rejected' delete action is recorded under the workload's rejected list."""
    spec = load()
    w = spec.workloads[0]
    _write(tmp_path / "status.jsonl", [
        {"run_id": "r7", "speed_multiplier": 720, "state": "RUNNING", "qualification": "QUALIFIED",
         "workloads": [{"id": w.id, "required_work": w.work_units, "completed_work": w.work_units,
                        "lost_work": 0.0, "output_ready_at": None, "final_output_delivered": True,
                        "assignments": [{"vm_id": "vm-a", "zone": "at-vie-1", "state": "running"}],
                        "succeeded_at": to_ts(w.deadline_h - 5)}]}])
    _write(tmp_path / "decisions.jsonl", [
        {"t": 10.0, "workload": w.id, "action": "create", "zone": "at-vie-1", "profile": "p1",
         "workers": 1, "block": [10, 30]},
        {"t": 50.0, "workload": w.id, "action": "rejected",
         "reason": "delete refused: 409 run finished"},
        {"t": 51.0, "workload": w.id, "action": "delete", "reason": "final output delivered"}])
    (tmp_path / "console.log").write_text('{"end": "all delivered and cleaned up", "t": 55.0}\n')
    run = analyze(tmp_path, spec)
    rw = run["workloads"][w.id]
    assert len(rw["rejected"]) == 1 and "409" in rw["rejected"][0]
    assert run["summary"]["rejected"] == 1
