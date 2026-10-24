"""The run analysis reads only the run's own logs and says where every delivery time came from."""
import json

from greenops.analyze import analyze
from greenops.spec import load, to_ts


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n{torn", encoding="utf-8")


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
