"""Export one scenario, run under several policies, as the JSON the UI reads.

    python -m greenops.export --seed 3 --out ui/data/run.json

The schema is documented in ui/README.md. On Friday, a second exporter can build the
same JSON from the real platform (allocation timeline, forecasts, work status), and
the UI works unchanged.
"""
from __future__ import annotations

import argparse
import json
import os

import math

from . import catalog as C
from .policy import Baseline, CarbonAware, Context, apply, options_for
from .scenario import ZONE_SITES, make_scenario
from .sim import Sim

FORECAST_EVERY_H = 6
FORECAST_LEN_H = 48


def run_traced(sc, policy, dt=0.25):
    sim = Sim(sc, dt=dt)
    ctx = Context(sc.zones, sc.profiles, sc.workloads, sc.quotas, sc.boot_h, forecast=sc.carbon.forecast, dt=dt)
    while sim.now < sc.horizon_h - 1e-9:
        apply(sim, ctx, policy.decide(ctx, sim.observe()))
        sim.step()
        if sim.disqualified:
            break
    sim._record()
    score = sim.score()
    wl = {}
    for w in sc.workloads:
        s = sim.ws[w.id]
        segs = [x for x in sim.segments if x["workload"] == w.id]
        first = min((x["start"] for x in segs), default=None)
        done = max((x["end"] for x in segs if x["phase"] == "delivering"), default=None)
        wl[w.id] = {
            "delivered": s.delivered, "failed": s.failed,
            "progress": round(s.progress / w.work_units, 4),
            "carbon_kg": round(sim.wl_carbon.get(w.id, 0.0) / 1000, 4),
            "first_start": first, "delivered_at": done,
            "waited_h": round(first - w.release_h, 2) if first is not None else None,
            "zones_used": sorted({x["zone"] for x in segs}),
        }
    return {
        "policy": policy.name,
        "score": score,
        "segments": [dict(x, start=round(x["start"], 2), end=round(x["end"], 2)) for x in sim.segments],
        "usage": sim.usage[::2],                  # every 30 min is plenty for the chart
        "carbon_series": sim.carbon_series,
        "workloads": wl,
        "decisions": getattr(policy, "decisions", []),
    }


START_UTC = "2026-10-23T18:00:00Z"   # simulated hour 0 = hacking starts, Fri 20:00 Vienna


def zone_record(z):
    rec = {"id": z.id, "country": z.country, "pue": z.pue}
    if z.id in ZONE_SITES:
        lat, lon, city, real = ZONE_SITES[z.id]
        rec.update(lat=lat, lon=lon, city=city, real_zone=real)
    return rec


def landscape(sc, w, horizon_fc=48):
    """Options the planner could see when the job was released: estimated carbon (forecast issued at
    release) for each allowed zone and each whole start hour, using the best VM type/worker count
    for that zone and hour. None = starting then would no longer be safe before the deadline."""
    pol = CarbonAware()
    ctx = Context(sc.zones, sc.profiles, sc.workloads, sc.quotas, sc.boot_h, forecast=sc.carbon.forecast)
    now = w.release_h
    curves = {z.id: pol._curve(ctx, z.id, now) for z in sc.zones}
    opts = options_for(ctx, w.id, w.work_units)
    zones = sorted({o.zone_id for o in opts})
    hours = list(range(math.ceil(now), int(w.deadline_h) + 1))
    grid = []
    for zid in zones:
        zo = [o for o in opts if o.zone_id == zid]
        row = []
        for h in hours:
            best = None
            for o in zo:
                if h > w.deadline_h - o.duration_h * pol.safety - pol.buffer_h:
                    continue
                g = pol._window_carbon(*curves[zid], now, h + ctx.boot_h, o.duration_h - ctx.boot_h, o.draw_kw)
                best = g if best is None else min(best, g)
            row.append(round(best, 1) if best is not None else None)
        grid.append(row)
    return {"issued_h": round(now, 2), "forecast_until_h": round(now + horizon_fc, 2), "zones": zones, "hours": hours, "grams": grid}


def build(seed: int, start_utc: str = START_UTC) -> dict:
    sc = make_scenario(seed)
    H = int(sc.horizon_h)
    return {
        "schema": 1,
        "source": "local simulator (synthetic practice scenario)",
        "seed": seed,
        "horizon_h": sc.horizon_h,
        "start_utc": start_utc,
        "zones": [zone_record(z) for z in sc.zones],
        "profiles": [{"id": p.id, "vcpus": p.vcpus, "mem_gb": p.mem_gb, "power_kw": p.power_kw,
                      "gpu_family": p.gpu_family, "gpus": p.gpus} for p in sc.profiles],
        "quotas": {"max_vms": sc.quotas.max_vms, "max_vcpus": sc.quotas.max_vcpus, "gpu_caps": sc.quotas.gpu_caps},
        "workloads": [{
            "id": w.id, "name": C.WORKLOAD_NAMES.get(w.id, w.id), "kind": w.kind, "release_h": round(w.release_h, 2), "deadline_h": round(w.deadline_h, 2),
            "work_units": round(w.work_units, 1), "setup_h": w.setup_h, "output_h": w.output_h,
            "allowed_countries": sorted(w.allowed_countries), "checkpoint_h": w.checkpoint_h,
            "max_workers": w.max_workers, "ref_energy_kwh": round(w.ref_energy_kwh, 2)} for w in sc.workloads],
        "carbon_actual": {z.id: [round(sc.carbon.at(z.id, h), 1) for h in range(H)] for z in sc.zones},
        "forecasts": {z.id: {str(t): [round(v, 1) for v in sc.carbon.forecast(z.id, t, FORECAST_LEN_H)]
                             for t in range(0, H, FORECAST_EVERY_H)} for z in sc.zones},
        "phase_names": C.PLATFORM_PHASES,
        "gpu_labels": C.GPU_LABELS,
        "landscapes": {w.id: landscape(sc, w) for w in sc.workloads},
        "runs": [run_traced(sc, CarbonAware()), run_traced(sc, Baseline())],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--start", default=START_UTC, help="real UTC time of simulated hour 0 (for satellite positions)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "ui", "data", "run.json"))
    a = ap.parse_args()
    data = build(a.seed, a.start)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    for r in data["runs"]:
        print(r["policy"], r["score"])
    print("wrote", os.path.abspath(a.out), os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
