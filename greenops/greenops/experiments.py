"""Experiment ladder: change one part of the policy at a time and measure it (the challenge's working method).

    python -m greenops.experiments --seeds 12          # prints a table, writes ui/data/experiments.json

Every rung runs on the same seeds, so differences come from the policy, not the scenario.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics

from .controller import run_sim
from .policy import Baseline, CarbonAware
from .scenario import make_scenario

LADDER = [
    ("baseline", "Baseline", "Fixed legal zone (first allowed), start at release, lowest-energy option that meets the deadline, delete VMs when done.",
     lambda: Baseline()),
    ("zone", "+ cleanest zone now", "Same timing, but each job starts in the legal zone, VM type and worker count with the lowest forecast carbon for starting now.",
     lambda: CarbonAware(allow_wait=False, name="zone")),
    ("wait", "+ wait for cleaner hours", "Also delays flexible jobs to the cleanest forecast window that still leaves a safety margin before the deadline.",
     lambda: CarbonAware(name="wait")),
    ("no-cleanup", "Ablation: keep idle VMs", "The full policy, but finished VMs are left running. Shows what deleting idle VMs is worth.",
     lambda: CarbonAware(keep_idle=True, name="no-cleanup")),
]


def run(seeds: int) -> dict:
    rungs = []
    for key, label, desc, make in LADDER:
        per = []
        for seed in range(seeds):
            r = run_sim(make_scenario(seed), make())
            per.append({"seed": seed, **{k: r.get(k) for k in ("score", "carbon_kg", "energy_kwh", "delivered", "all_done_bonus", "disqualified")}})
        ok = [p for p in per if not p.get("disqualified")]
        rungs.append({
            "key": key, "label": label, "change": desc,
            "score_mean": round(statistics.mean(p["score"] for p in per)),
            "score_min": min(p["score"] for p in per), "score_max": max(p["score"] for p in per),
            "carbon_mean": round(statistics.mean(p["carbon_kg"] for p in ok), 2) if ok else None,
            "energy_mean": round(statistics.mean(p["energy_kwh"] for p in ok), 1) if ok else None,
            "delivered_mean": round(statistics.mean(p["delivered"] for p in ok), 2) if ok else None,
            "all_done": sum(bool(p["all_done_bonus"]) for p in per),
            "disqualified": sum(bool(p.get("disqualified")) for p in per),
            "runs": per,
        })
    return {"schema": 1, "seeds": seeds, "source": "local simulator, practice scenarios shaped like the real challenge",
            "note": "Score uses a stand-in formula until the organizers' frozen scoring policy is plugged in.",
            "rungs": rungs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "ui", "data", "experiments.json"))
    a = ap.parse_args()
    d = run(a.seeds)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    print(f"{'rung':28s} {'score':>8s} {'carbon kg':>10s} {'kWh':>7s} {'delivered':>9s} {'all done':>8s} {'DQ':>3s}")
    for r in d["rungs"]:
        print(f"{r['label']:28s} {r['score_mean']:8d} {r['carbon_mean']:10.2f} {r['energy_mean']:7.1f} "
              f"{r['delivered_mean']:9.2f} {r['all_done']:>4d}/{d['seeds']:<3d} {r['disqualified']:3d}")
    print("wrote", os.path.abspath(a.out))


if __name__ == "__main__":
    main()
