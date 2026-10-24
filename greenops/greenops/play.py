"""Play a planner against the offline Game and compare policies on synthetic practice grids.

    python -m greenops.play --seeds 10

Policies: naive (start at release, first legal zone, fastest profile, run straight),
zone (our placement, no pausing), carbon-aware (placement + pause through dirty hours).
"""
from __future__ import annotations

import argparse
import statistics

from .game import Game, make_grid
from .guard import check_placement, is_allowed
from .model import suitable, throughput
from .planner import Planner, Placement
from .spec import Spec, load


class Naive(Planner):
    """Without carbon awareness: first legal zone (alphabetical), fastest profile, start when quota allows."""

    def __post_init__(self):
        super().__post_init__()
        self.stretch, self.shift, self.commit_h, self.slack_h = (1.0,), False, -1, 0

    def _candidates(self, w, est):
        for z in sorted(self.spec.zones, key=lambda z: z.id):
            ps = [p for p in self.spec.profiles if is_allowed(w, z) and p.available_in(z.id) and suitable(p, w)]
            if ps:
                return [Placement(z.id, max(ps, key=lambda p: throughput(p, w)).id, 1)]
        return []


def policies(spec: Spec, forecast):
    return [Naive(spec, forecast, pause=False, name="naive"),
            Planner(spec, forecast, pause=False, shift=False, name="+zone"),
            Planner(spec, forecast, pause=False, name="+zone+shift"),
            Planner(spec, forecast, name="carbon-aware")]


def apply(game: Game, planner: Planner, actions) -> None:
    for act in actions:
        kind = act[0]
        try:
            if kind == "create":
                _, wid, zone, prof, _i = act
                check_placement(game.W[wid], game.Z[zone])
                vid = game.create(wid, zone, prof)
                planner.vm_profile[vid] = prof
            elif kind == "stop":
                game.stop(act[1])
            elif kind == "start":
                game.start(act[1])
            elif kind == "delete":
                game.delete(act[1])
        except ValueError as e:          # quota or worker limit: the planner retries next tick
            planner.rejected(game.now, act, str(e))


def run(spec: Spec, seed: int, make_planner, tick_h: float = 0.25):
    grid = make_grid(seed, {s.area for s in spec.sites.values()})
    planner = make_planner(spec, grid.forecast)
    game = Game(spec, grid)
    next_tick = 0.0
    while game.now < spec.horizon_h - 1e-9 and not game.disqualified:
        if game.now + 1e-9 >= next_tick:
            st = game.status()
            apply(game, planner, planner.decide(st))
            next_tick += tick_h
        game.step()
    return game, planner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    a = ap.parse_args()
    spec = load()
    names = [p.name for p in policies(spec, None)]
    res = {n: [] for n in names}
    for seed in range(a.seeds):
        for i, n in enumerate(names):
            game, _ = run(spec, seed, lambda s, f, i=i: policies(s, f)[i])
            res[n].append(game.score())
    for n in names:
        rs = res[n]
        print(f"{n:13s} score {statistics.mean(r['score'] for r in rs):8.0f}  "
              f"carbon {statistics.mean(r['carbon_kg'] for r in rs):7.3f} kg  "
              f"energy {statistics.mean(r['energy_kwh'] for r in rs):7.2f} kWh  "
              f"on time {min(r['delivered'] for r in rs)}-{max(r['delivered'] for r in rs)}/15")


if __name__ == "__main__":
    main()
