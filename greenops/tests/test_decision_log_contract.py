"""Decision-log contract: analyze.py must correctly interpret a planner decision log written
in the live decisions.jsonl format, using only the data the Control Room relies on.

The fields the Control Room and analyze.py use from each decision line:
    t, workload, action, reason, zone, profile, workers, block, run_hours, est_kg, vms
"""
import json

from greenops.analyze import analyze
from greenops.planner import Planner
from greenops.play import run as play
from greenops.spec import load, to_ts


def test_analyze_reads_the_planners_decision_log(tmp_path):
    """Play the real planner on the offline game (seed 11), write its own decision log and a final
    status line in the live work-status shape, then verify analyze reproduces the game's results."""
    spec = load()
    game, planner = play(spec, 11, Planner)

    assert not game.disqualified
    score = game.score()
    assert score["delivered"] == 15

    # Build a single final status.jsonl line in the live work-status shape
    final_st = game.status()
    wl_rows = []
    for wid in game.W:
        gs = game.ws[wid]
        w = game.W[wid]
        wl_rows.append({
            "id": wid,
            "state": "x",
            "required_work": str(w.work_units),
            "completed_work": str(gs.completed),
            "work_unit": "vcpu_hour",
            "lost_work": str(gs.lost),
            "output_ready_at": gs.output_ready_h,
            "succeeded_at": to_ts(gs.delivered_h) if gs.delivered_h is not None else None,
            "final_output_delivered": gs.delivered_h is not None,
            "assignments": [{"vm_id": v.id, "zone": v.zone_id, "state": v.state}
                            for v in game.vms.values() if v.workload_id == wid],
        })
    status_line = {
        "run_id": "contract-test",
        "virtual_time": to_ts(game.now),
        "speed_multiplier": 720,
        "state": "COMPLETED",
        "qualification": final_st["qualification"],
        "workloads": wl_rows,
    }

    # Write decisions.jsonl in the live format
    (tmp_path / "decisions.jsonl").write_text(
        "\n".join(json.dumps(d) for d in planner.decisions) + "\n", encoding="utf-8"
    )
    (tmp_path / "status.jsonl").write_text(json.dumps(status_line) + "\n", encoding="utf-8")
    (tmp_path / "console.log").write_text(
        json.dumps({"end": "all delivered and cleaned up", "t": game.now}) + "\n",
        encoding="utf-8",
    )

    run = analyze(tmp_path, spec)

    # 15 delivered; every slack_h matches the game's deadline_h - delivered_h within 0.01
    assert run["summary"]["delivered"] == 15
    assert run["summary"]["on_time"] == 15
    for wid in game.W:
        w = game.W[wid]
        rw = run["workloads"][wid]
        gs = game.ws[wid]
        if gs.delivered_h is not None:
            expected_slack = w.deadline_h - gs.delivered_h          # analyze rounds both ends to 0.01 h
            assert abs(rw["slack_h"] - expected_slack) <= 0.01 + 1e-9, (
                f"{w.id}: analyze slack={rw['slack_h']} != game slack={expected_slack:.3f}"
            )
        else:
            assert rw["slack_h"] is None

    # Every create in the log has zone, workers and block
    for d in planner.decisions:
        if d["action"] == "create":
            assert "zone" in d and d["zone"] is not None, f"create missing zone: {d}"
            assert "workers" in d and d["workers"] is not None, f"create missing workers: {d}"
            assert "block" in d and d["block"] is not None, f"create missing block: {d}"
