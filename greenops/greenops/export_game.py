"""Export the real-challenge path for the Control Room and Earth view (schema 1, see ui/README.md).

    python -m greenops.export_game --seed 3                  # writes ui/data/run.json
    python -m greenops.export_game --seed 3 --ladder 8       # ... and ui/data/experiments.json

Same 15 workloads, 11 zones, quotas and score constants as the challenge (greenops/challenge/), the
same planner that runs live (planner.py) and the naive scheduler as the baseline, played on the
offline game (game.py) with a SYNTHETIC grid. No real-run electricity or carbon values (rule 2).
The decision log is the planner's own, in the live decisions.jsonl format.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from multiprocessing import Pool

from .game import Game, make_grid
from .play import Naive, apply, policies
from .planner import Planner
from .scenario import ZONE_SITES
from .spec import load

START_UTC = "2026-10-23T18:00:00Z"   # simulated hour 0 for the Earth view's sun and satellites
FORECAST_EVERY_H = 6
FORECAST_LEN_H = 24                  # what the live API serves (48 and 72 are rejected)
SOURCE = "offline game: the challenge's real jobs, zones, quotas and planner on a synthetic grid"

LADDER = [  # (key, label, what changed) for play.policies(), in order
    ("naive", "Naive scheduler", "First legal zone (alphabetical), fastest machine, start as soon as quota allows, run straight through."),
    ("zone", "+ where and which machine", "Each job goes to the legal zone and machine with the lowest forecast PUE x g/kWh x kW."),
    ("shift", "+ when to start", "Also moves each job's start to the cleanest forecast window that still meets the deadline."),
    ("carbon-aware", "+ stop through dirty hours", "The full planner: a block of hours per job, run in its cleanest hours, stopped in the others."),
]


def _phase(game, v) -> str:
    w, s = game.W.get(v.workload_id), game.ws.get(v.workload_id)
    if v.state == "creating":
        return "booting"
    if v.state == "stopped":
        return "stopped"
    if s is None or s.delivered_h is not None:
        return "done"
    if game.now + 1e-9 < w.release_h:
        return "waiting"
    if s.output_left is not None:
        return "delivering"
    return "setup" if v.input_left > 1e-9 else "running"


def trace(spec, grid, planner, tick_h: float = 0.25) -> dict:
    """Play one policy; record each VM's phases, quota use and cumulative carbon."""
    game, H = Game(spec, grid), int(spec.horizon_h)
    P = {p.id: p for p in spec.profiles}
    open_seg, segs, usage, series = {}, [], [], []
    nxt, sample = 0.0, 0.0
    while game.now < spec.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= nxt:
            apply(game, planner, planner.decide(game.status()))
            nxt += tick_h
        t = round(game.now, 4)
        live = {}
        for v in game.vms.values():
            ph = _phase(game, v)
            live[v.id] = ph
            cur = open_seg.get(v.id)
            if cur and cur["phase"] == ph:
                continue
            if cur:
                cur["end"] = t
                segs.append(cur)
            open_seg[v.id] = {"vm": v.id, "workload": v.workload_id, "zone": v.zone_id, "profile": _label(P[v.profile_id]),
                              "phase": ph, "start": t, "end": None}
        for vid in [k for k in open_seg if k not in live]:          # deleted
            seg = open_seg.pop(vid)
            seg["end"] = t
            segs.append(seg)
        if game.now + 1e-9 >= sample:
            gpus = {}
            for v in game.vms.values():
                p = P[v.profile_id]
                if p.gpu_family:
                    gpus[p.gpu_family] = gpus.get(p.gpu_family, 0) + p.gpus
            usage.append({"t": round(game.now, 2), "vms": len(game.vms),
                          "vcpus": sum(P[v.profile_id].vcpus for v in game.vms.values()), "gpus": gpus})
            series.append({"t": round(game.now, 2),
                           "carbon_kg": round((sum(s.carbon_g for s in game.ws.values()) + game.unbound_g) / 1000, 3)})
            sample += 0.5
        game.step()
    for seg in open_seg.values():
        seg["end"] = round(game.now, 4)
        segs.append(seg)
    score = game.score()
    score["all_done_bonus"] = bool(score.get("all_done"))
    wl = {}
    for w in spec.workloads:
        s, mine = game.ws[w.id], [x for x in segs if x["workload"] == w.id]
        first = min((x["start"] for x in mine), default=None)
        on_time = s.delivered_h is not None and s.delivered_h <= w.deadline_h + 1e-9
        wl[w.id] = {"delivered": on_time, "carbon_kg": round(s.carbon_g / 1000, 4),
                    "first_start": None if first is None else round(first, 2),
                    "delivered_at": None if s.delivered_h is None else round(s.delivered_h, 2),
                    "slack_h": None if s.delivered_h is None else round(w.deadline_h - s.delivered_h, 2),
                    "waited_h": None if first is None else round(max(0.0, first - w.release_h), 2),
                    "zones_used": sorted({x["zone"] for x in mine})}
    return {"policy": planner.name, "score": score,
            "segments": [dict(x, start=round(x["start"], 2), end=round(x["end"], 2)) for x in segs if x["end"] > x["start"]],
            "usage": usage, "carbon_series": series, "workloads": wl, "decisions": planner.decisions}


def _label(p) -> str:
    return f"{p.gpus}x {p.gpu_family}" if p.gpu_family else f"{p.vcpus} vCPU"


def build(seed: int, start_utc: str = START_UTC) -> dict:
    spec = load()
    H = int(spec.horizon_h)
    grid = make_grid(seed, {s.area for s in spec.sites.values()})
    area = {z.id: spec.sites[z.id].area for z in spec.zones}
    zones = []
    for z in spec.zones:
        site = spec.sites[z.id]
        rec = {"id": z.id, "country": z.country, "pue": z.pue, "city": site.city, "lat": site.lat, "lon": site.lon}
        if z.id in ZONE_SITES:
            rec["real_zone"] = ZONE_SITES[z.id][3]
        zones.append(rec)
    runs = [trace(spec, grid, Planner(spec, grid.forecast)),
            trace(spec, grid, Naive(spec, grid.forecast, pause=False, name="naive"))]
    return {
        "schema": 1, "source": f"{SOURCE} (seed {seed})", "seed": seed, "horizon_h": spec.horizon_h,
        "start_utc": start_utc, "forecast_h": FORECAST_LEN_H,
        "score_label": "Score (offline, v2 formula)",
        "score_note": "greenops-score-v2 constants from the challenge rules, computed by the offline game; "
                      "the competition score is only on the platform dashboard.",
        "zones": zones,
        "profiles": [{"id": p.id, "label": _label(p), "vcpus": p.vcpus, "mem_gb": p.mem_gb, "power_kw": p.power_kw,
                      "gpu_family": p.gpu_family, "gpus": p.gpus} for p in spec.profiles],
        "quotas": {"max_vms": spec.quotas.max_vms, "max_vcpus": spec.quotas.max_vcpus, "gpu_caps": spec.quotas.gpu_caps},
        "workloads": [{"id": w.id, "name": getattr(w, "title", None) or w.id, "kind": w.kind,
                       "release_h": round(w.release_h, 2), "deadline_h": round(w.deadline_h, 2),
                       "work_units": round(w.work_units, 1), "setup_h": w.setup_h, "output_h": w.output_h,
                       "allowed_countries": sorted(w.allowed_countries), "checkpoint_h": w.checkpoint_h,
                       "max_workers": w.max_workers, "ref_energy_kwh": round(w.ref_energy_kwh, 3)}
                      for w in spec.workloads],
        "carbon_actual": {z.id: [round(grid.at(area[z.id], h), 1) for h in range(H)] for z in spec.zones},
        "forecasts": {z.id: {str(t): [round(v, 1) for v in grid.forecast(area[z.id], t, FORECAST_LEN_H)]
                             for t in range(0, H, FORECAST_EVERY_H)} for z in spec.zones},
        "runs": runs,
    }


def _bench(args):
    i, seed = args
    spec = load()
    grid = make_grid(seed, {s.area for s in spec.sites.values()})
    game = Game(spec, grid)
    planner = policies(spec, grid.forecast)[i]
    nxt = 0.0
    while game.now < spec.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= nxt:
            apply(game, planner, planner.decide(game.status()))
            nxt += 0.25
        game.step()
    return i, seed, game.score()


def ladder(seeds: int, procs: int = 4) -> dict:
    """One change at a time on the same synthetic grids (play.policies), for the ladder card."""
    jobs = [(i, s) for i in range(len(LADDER)) for s in range(seeds)]
    with Pool(procs) as pool:
        res = pool.map(_bench, jobs)
    rungs = []
    for i, (key, label, change) in enumerate(LADDER):
        rs = [sc for j, _s, sc in sorted(res) if j == i]
        rungs.append({"key": key, "label": label, "change": change,
                      "score_mean": round(statistics.mean(r["score"] for r in rs)),
                      "carbon_mean": round(statistics.mean(r["carbon_kg"] for r in rs), 2),
                      "carbon_sd": round(statistics.pstdev(r["carbon_kg"] for r in rs), 2),
                      "energy_mean": round(statistics.mean(r["energy_kwh"] for r in rs), 1),
                      "all_done": sum(bool(r.get("all_done")) for r in rs),
                      "disqualified": sum(bool(r.get("disqualified")) for r in rs)})
    return {"schema": 1, "seeds": seeds, "source": f"python -m greenops.export_game --ladder {seeds}",
            "note": "Offline game, synthetic grids (seeds 0.." + str(seeds - 1) + "), the challenge's real spec.", "rungs": rungs}


def main():
    here = os.path.join(os.path.dirname(__file__), "..", "ui", "data")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--start", default=START_UTC, help="real UTC time of simulated hour 0 (Earth view)")
    ap.add_argument("--out", default=os.path.join(here, "run.json"))
    ap.add_argument("--ladder", type=int, default=0, help="also write experiments.json over this many seeds")
    a = ap.parse_args()
    data = build(a.seed, a.start)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    for r in data["runs"]:
        print(r["policy"], {k: r["score"][k] for k in ("score", "carbon_kg", "delivered") if k in r["score"]})
    print("wrote", os.path.abspath(a.out), os.path.getsize(a.out), "bytes")
    if a.ladder:
        e = ladder(a.ladder)
        out = os.path.join(os.path.dirname(os.path.abspath(a.out)), "experiments.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(e, f, indent=1)
        for r in e["rungs"]:
            print(f"{r['label']:28s} {r['carbon_mean']:6.2f} ± {r['carbon_sd']:.2f} kg  score {r['score_mean']:,}")
        print("wrote", out)


if __name__ == "__main__":
    main()
