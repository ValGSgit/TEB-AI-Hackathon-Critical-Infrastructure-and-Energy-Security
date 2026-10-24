"""What a live run did, from its own logs, with the source of every number.

    python -m greenops.analyze .local/run2 [.local/run3 ...]

Reads decisions.jsonl, status.jsonl and console.log from each folder (as written by greenops.live).
Deadlines and releases come from challenge/workloads.json; delivery times are the platform's own
`succeeded_at`. Status is sampled once per simulated hour, so a job delivered after the last sample is
dated by our delete decision (sent only once the platform reports final_output_delivered): an upper bound.
Each value is printed with the file and line it came from, so it can be checked by hand. Carbon and
score are not in these logs: they come from the platform dashboard for the printed run ID.

Real-run values stay out of git (rule 2): write the report into the run's .local folder.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .spec import load, to_h


def _lines(path: Path):
    """(line number, record) for every parseable line; a crash can leave a torn last line."""
    if not path.exists():
        return
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            yield i, json.loads(line)
        except json.JSONDecodeError:
            continue


def analyze(folder: Path, spec=None) -> dict:
    spec = spec or load()
    W = {w.id: w for w in spec.workloads}
    st, de = folder / "status.jsonl", folder / "decisions.jsonl"
    run = {"folder": str(folder), "run_id": None, "speed": None, "qualification": None, "final_state": None,
           "samples": 0, "workloads": {}, "restarts": 0, "end": None}
    rows = {wid: {"deadline_h": round(w.deadline_h, 2), "release_h": round(w.release_h, 2),
                  "source_deadline": "challenge/workloads.json deadline_at",
                  "delivered_h": None, "source_delivered": None, "slack_h": None,
                  "first_planned_start": None, "source_first_plan": None,
                  "created_h": None, "planned_block": None, "source_created": None,
                  "deleted_h": None, "idle_after_delivery_h": None,
                  "blocked": [], "rejected": [], "zone": None, "profile": None, "workers": None}
            for wid, w in W.items()}
    for n, s in _lines(st):
        run["samples"] += 1
        run["run_id"] = run["run_id"] or s.get("run_id")
        run["speed"] = s.get("speed_multiplier", run["speed"])
        run["qualification"], run["final_state"] = s.get("qualification"), s.get("state")
        run["source_qualification"] = f"{st.name}:{n}"
        for w in s.get("workloads", []):
            r = rows.get(w["id"])
            if r is None or r["delivered_h"] is not None or not w.get("final_output_delivered"):
                continue
            ts = w.get("succeeded_at") or w.get("output_ready_at")
            if ts:
                r["delivered_h"] = round(to_h(ts), 2)
                r["slack_h"] = round(r["deadline_h"] - r["delivered_h"], 2)
                r["source_delivered"] = f"{st.name}:{n} succeeded_at={ts}"
    for n, d in list(_lines(de)) + [(n, d) for n, d in _lines(folder / "console.log") if "end" in d]:
        if "end" in d:
            run["end"] = {"t": round(d["t"], 2), "why": d["end"], "source": f"console.log:{n}"}
            continue
        r = rows.get(d.get("workload"))
        if r is None:
            continue
        a, src = d.get("action"), f"{de.name}:{n}"
        if a == "wait" and r["first_planned_start"] is None:
            m = re.search(r"planned start at hour (\d+)", d.get("reason", ""))
            if m:
                r["first_planned_start"], r["source_first_plan"] = int(m.group(1)), f"{src} t={d['t']}"
        elif a == "create" and r["created_h"] is None:      # a retried create after a restart is not a new start
            r["created_h"], r["planned_block"], r["source_created"] = d["t"], d.get("block"), src
            r["zone"], r["profile"], r["workers"] = d.get("zone"), d.get("profile"), d.get("workers")
        elif a == "adopt":
            run["restarts"] += 1
            r["zone"] = r["zone"] or d.get("zone")
        elif a == "delete" and r["deleted_h"] is None:
            r["deleted_h"] = d["t"]
            if r["delivered_h"] is None:            # delivered after the last status sample
                r["delivered_h"], r["slack_h"] = d["t"], round(r["deadline_h"] - d["t"], 2)
                r["source_delivered"] = f"{src} delete after final_output_delivered (upper bound)"
        elif a == "blocked":
            r["blocked"].append(f"t={d['t']} ({src})")
        elif a == "rejected":
            r["rejected"].append(f"t={d['t']} {d.get('reason', '')} ({src})")
    for r in rows.values():
        if r["deleted_h"] is not None and r["delivered_h"] is not None:
            r["idle_after_delivery_h"] = round(max(0.0, r["deleted_h"] - r["delivered_h"]), 2)
    run["workloads"] = rows
    done = [r for r in rows.values() if r["slack_h"] is not None]
    run["summary"] = {
        "delivered": len(done), "of": len(rows),
        "on_time": sum(r["slack_h"] >= 0 for r in done),
        "min_slack_h": min((r["slack_h"] for r in done), default=None),
        "tightest": min(rows, key=lambda k: rows[k]["slack_h"] if rows[k]["slack_h"] is not None else 1e9),
        "blocked": sum(len(r["blocked"]) for r in rows.values()),
        "rejected": sum(len(r["rejected"]) for r in rows.values()),
        "created_later_than_first_plan_h": {
            k: round(r["created_h"] - r["first_planned_start"], 1) for k, r in rows.items()
            if r["created_h"] is not None and r["first_planned_start"] is not None},
        "max_idle_after_delivery_h": max((r["idle_after_delivery_h"] or 0 for r in rows.values()), default=0),
    }
    return run


def report(run: dict) -> str:
    s = run["summary"]
    out = [f"## {run['folder']}",
           f"run {run['run_id']} at {run['speed']}x; last sample: {run['final_state']}, {run['qualification']}"
           f" ({run.get('source_qualification')}); {run['samples']} status samples; restarts (adopt): {run['restarts']}",
           f"end: {run['end']}" if run["end"] else "end: no end record (run stopped early or still going)",
           f"delivered {s['delivered']}/{s['of']}, on time {s['on_time']}; tightest {s['tightest']} "
           f"at {s['min_slack_h']} h before its deadline; blocked {s['blocked']}; rejected {s['rejected']}; "
           f"max idle after delivery {s['max_idle_after_delivery_h']} h",
           "", "| workload | release | deadline | delivered | slack h | first plan | created | drift h | zone | workers | source of delivery |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for wid, r in run["workloads"].items():
        drift = s["created_later_than_first_plan_h"].get(wid)
        out.append(f"| {wid} | {r['release_h']} | {r['deadline_h']} | {r['delivered_h']} | {r['slack_h']} | "
                   f"{r['first_planned_start']} | {r['created_h']} | {drift} | {r['zone']} | {r['workers']} | "
                   f"{r['source_delivered']} |")
    for wid, r in run["workloads"].items():
        for b in r["blocked"]:
            out.append(f"- blocked: {wid} {b}")
        for b in r["rejected"]:
            out.append(f"- rejected: {wid} {b}")
    out.append("\nCarbon and score: platform dashboard for this run ID (not in these logs).")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="also write analysis.json into each folder")
    a = ap.parse_args()
    spec = load()
    for f in a.folders:
        run = analyze(f, spec)
        print(report(run), "\n")
        if a.json:
            (f / "analysis.json").write_text(json.dumps(run, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
