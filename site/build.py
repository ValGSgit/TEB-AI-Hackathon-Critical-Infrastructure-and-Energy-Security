"""Build the GitHub Pages site: site/template.html + data from the offline game -> <out>/index.html.

    python site/build.py                 # writes site/dist/ (git-ignored)
    python site/build.py --out _site     # what the Pages workflow does

Everything shown is from the offline game in greenops/game.py on SYNTHETIC grids (generic
country profiles, random per seed). No real-run electricity or carbon values are used (rule 2).
The Control Room and Earth pages are copied in when they have been built.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "greenops"))

from greenops.game import Game, make_grid           # noqa: E402
from greenops.play import apply, policies           # noqa: E402
from greenops.spec import load                      # noqa: E402

SPEC = load()
REPLAY_SEED = 3
BENCH_SEEDS = range(8)
NAMES = ["naive", "+zone", "+zone+shift", "carbon-aware"]


def trace(policy_index: int, seed: int) -> dict:
    """Run one policy and record, per workload and hour: state, zone and grams emitted."""
    grid = make_grid(seed, {s.area for s in SPEC.sites.values()})
    planner = policies(SPEC, grid.forecast)[policy_index]
    game = Game(SPEC, grid)
    H = int(SPEC.horizon_h)
    W = [w.id for w in SPEC.workloads]
    state = {w: [{} for _ in range(H)] for w in W}       # hour -> {state: samples}
    grams = {w: [0.0] * H for w in W}
    zone = {w: None for w in W}
    vcpu = [0.0] * H
    carbon = [0.0] * (H + 1)
    P = {p.id: p for p in SPEC.profiles}
    next_tick = 0.0
    while game.now < SPEC.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= next_tick:
            apply(game, planner, planner.decide(game.status()))
            next_tick += 0.25
        h = min(int(game.now + 1e-9), H - 1)
        before = {w: game.ws[w].carbon_g for w in W}
        for v in game.vms.values():
            w = game.W[v.workload_id]
            s = game.ws[v.workload_id]
            if v.state == "stopped":
                k = "s"
            elif v.state == "creating" or game.now + 1e-9 < w.release_h or s.delivered_h is not None:
                k = "w"
            else:
                k = "r"
            cell = state[v.workload_id][h]
            cell[k] = cell.get(k, 0) + 1
            zone[v.workload_id] = v.zone_id
        vcpu[h] = max(vcpu[h], sum(P[v.profile_id].vcpus for v in game.vms.values()))
        game.step()
        for w in W:
            grams[w][h] += game.ws[w].carbon_g - before[w]
        carbon[min(int(game.now + 1e-9), H)] = sum(x.carbon_g for x in game.ws.values()) + game.unbound_g
    for i in range(1, H + 1):                            # carry the cumulative total over empty hours
        carbon[i] = max(carbon[i], carbon[i - 1])
    rows = []
    for w in SPEC.workloads:
        cells = "".join(max(c, key=c.get) if c else "." for c in state[w.id])
        rows.append({"id": w.id, "title": w.title, "kind": w.kind, "zone": zone[w.id],
                     "release": w.release_h, "deadline": w.deadline_h, "states": cells,
                     "grams": [round(g) for g in grams[w.id]],
                     "delivered": game.ws[w.id].delivered_h})
    score = game.score()
    return {"policy": NAMES[policy_index], "jobs": rows, "carbon_kg": [round(c / 1000, 3) for c in carbon],
            "vcpu": [round(v) for v in vcpu], "score": score}


def bench(args):
    i, seed = args
    grid = make_grid(seed, {s.area for s in SPEC.sites.values()})
    planner = policies(SPEC, grid.forecast)[i]
    game = Game(SPEC, grid)
    nxt = 0.0
    while game.now < SPEC.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= nxt:
            apply(game, planner, planner.decide(game.status()))
            nxt += 0.25
        game.step()
    return NAMES[i], game.score()


def build_data() -> dict:
    grid = make_grid(REPLAY_SEED, {s.area for s in SPEC.sites.values()})
    with Pool(2) as pool:
        results = pool.map(bench, [(i, s) for i in range(len(NAMES)) for s in BENCH_SEEDS])
        replays = pool.map(lambda_trace, [0, 3])
    summary = []
    for n in NAMES:
        rs = [r for name, r in results if name == n]
        c = [r["carbon_kg"] for r in rs]
        summary.append({"policy": n, "carbon_kg": round(statistics.mean(c), 2), "carbon_sd": round(statistics.pstdev(c), 2),
                        "energy_kwh": round(statistics.mean(r["energy_kwh"] for r in rs), 1),
                        "score": round(statistics.mean(r["score"] for r in rs)),
                        "on_time_min": min(r["delivered"] for r in rs)})
    zones = [{"id": z.id, "country": z.country, "pue": z.pue, "city": SPEC.sites[z.id].city} for z in SPEC.zones]
    H = int(SPEC.horizon_h)
    intensity = {a: [round(v) for v in grid.actual[a][:H]] for a in sorted(grid.actual)}
    return {"seed": REPLAY_SEED, "seeds": len(BENCH_SEEDS), "horizon": H, "zones": zones,
            "intensity": intensity, "replays": replays, "bench": summary}


def lambda_trace(i):           # picklable for multiprocessing
    return trace(i, REPLAY_SEED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site" / "dist"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = build_data()
    html = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    sources = ROOT / "greenops" / "ui" / "data" / "sources.json"       # shared with the Control Room
    if sources.exists():
        html = html.replace("/*__SOURCES__*/null", json.dumps(json.loads(sources.read_text(encoding="utf-8"))).replace("</", "<\/"))
    (out / "index.html").write_text(html, encoding="utf-8")
    # the two explainer pages link to each other by repo path; on the site they live at /control-room/ and /earth/
    links = {"../ui/dashboard.html": "../control-room/", "../globe/earth.html": "../earth/"}
    for src, dst in [("greenops/ui/dashboard.html", "control-room/index.html"),
                     ("greenops/globe/earth.html", "earth/index.html")]:
        if (ROOT / src).exists():
            page = (ROOT / src).read_text(encoding="utf-8")
            for a, b in links.items():
                page = page.replace(f'href="{a}"', f'href="{b}"')
            (out / dst).parent.mkdir(parents=True, exist_ok=True)
            (out / dst).write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    for b in data["bench"]:
        print(b)
    print("wrote", out / "index.html", (out / "index.html").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
