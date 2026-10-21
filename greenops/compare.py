"""Compare policies on many synthetic scenarios: python compare.py [n_seeds]"""
import sys, statistics, time
from greenops.scenario import make_scenario
from greenops.controller import run_sim
from greenops.policy import Baseline, CarbonAware

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
rows = {}
t0 = time.time()
for seed in range(n):
    sc = make_scenario(seed)
    for pol in (Baseline(), CarbonAware()):
        r = run_sim(sc, pol)
        rows.setdefault(pol.name, []).append(r)
        print(seed, pol.name, r)
print()
for name, rs in rows.items():
    print(f"{name:13s} score {statistics.mean(r['score'] for r in rs):8.0f}  "
          f"carbon {statistics.mean(r.get('carbon_kg', 0) for r in rs):7.1f} kg  "
          f"delivered {statistics.mean(r.get('delivered', 0) for r in rs):.1f}/15  "
          f"all-done {sum(r.get('all_done_bonus', False) for r in rs)}/{len(rs)}  "
          f"DQ {sum('disqualified' in r for r in rs)}")
print(f"{time.time()-t0:.1f}s")
