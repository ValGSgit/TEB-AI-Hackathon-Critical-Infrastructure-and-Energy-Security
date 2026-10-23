# GreenOps orchestrator (Exoscale GreenOps Challenge)

Carbon-aware orchestrator for the TEB Critical Infrastructure Hackathon, 23–25 Oct 2026. It drives the
challenge simulator's Exoscale-compatible API and schedules the 15 workloads over the 120-hour run with as
little electricity carbon as it can, using only the run's own grid forecasts.

## Real-challenge path

The public challenge spec (starter kit commit `a1dd55e`) is vendored in `challenge/` and checked against the
SHA-256 values in `challenge/manifest.json` on every load. `.gitattributes` keeps those files byte-exact on
Windows checkouts.

| File | What it does |
| --- | --- |
| `greenops/spec.py` | Loads zones, sites, profiles, workloads, quotas and score constants from `challenge/` |
| `greenops/guard.py` | Residency: `resolve_residency` (ANYWHERE / EU without CH / country, allow list narrows, forbid list wins) and `check_placement`, which every create goes through twice (planner and live client) |
| `greenops/planner.py` | Rolling-horizon slot planner, re-planned every simulated hour (below) |
| `greenops/live.py` | Control loop against the real API: endpoint checks and the run-only adapter from the starter kit, client-side rate limit, idempotent create names, adoption of existing VMs after a restart |
| `greenops/game.py` | Offline game with the real rules (stop/resume, per-worker input, sync overhead, output, idle until delete, quotas, residency DQ) on a **synthetic** per-country grid, for practice only |
| `greenops/play.py` | Compares naive, +zone, +zone+shift and carbon-aware on the offline game |
| `tests/fake_platform.py` | HTTP fake of the API subset `live.py` uses, served over the offline game |

### How the planner decides

- Cost of running a workload in hour *t* = kW (profile × workers) × zone PUE × estimated g/kWh. Inside
  the 24-hour forecast the estimate is the forecast. Beyond it, it is a 50/50 blend of the same hour's
  forecast value and the forecast mean, plus a 10% risk premium, so known clean hours beat guesses.
- Stopped VMs keep their quota. Each job therefore gets a **block** [start, start+L), with L between 1× and
  2× its run time. Its **run hours** are the cleanest hours inside the block, and the job is stopped in the
  others. Quota (vCPUs, GPU cards, VM count) is reserved for the whole block.
- Jobs are planned least flexible first, already-created ones first. Placement (zone, profile, workers) is
  chosen among residency-legal zones only, with faster worker counts as fallbacks. Every job aims to
  finish 2 h before its deadline.
- Actions each tick: delete (after `final_output_delivered`), stop, start, create. The first create runs
  while the run is READY, because the run clock starts at the first accepted create. A refused action is
  forgotten and re-planned. Every change goes to a decision log with its reason.

### Run

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 34 tests (on Windows: set PYTHONUTF8=1 for the exoscale package)
python -m greenops.play --seeds 4         # policy comparison on the offline game
python -m greenops.live --config greenops-exo.json      # live run (or the env vars below)
```

Credentials never go in git: either the run's CLI config `greenops-exo.json` (git-ignored) or
`EXOSCALE_API_KEY`, `EXOSCALE_API_SECRET`, `GREENOPS_CLOUD_ENDPOINT`, plus `GREENOPS_GRID_ENDPOINT` and
`GREENOPS_GRID_SECRET`. The loop writes `decisions.jsonl` and `status.jsonl` to `--out`
(default `/tmp/greenops-run`).

### Container (what the judges run)

```bash
docker build -t greenops greenops
docker run --rm --read-only --tmpfs /tmp --cpus 2 --memory 1g   -e EXOSCALE_API_KEY -e EXOSCALE_API_SECRET -e GREENOPS_CLOUD_ENDPOINT   -e GREENOPS_GRID_ENDPOINT -e GREENOPS_GRID_SECRET greenops
```

The image is `python:3.13-slim` with pinned `exoscale==0.16.3`, `requests==2.34.2` and `numpy==2.2.6`. It runs
as a non-root user and writes only to `/tmp`. A full 120-hour run against the fake platform inside the
container, with these limits (1 s polling = 0.2 simulated hours at 720×), delivered 15/15 at 53 MiB peak
memory. Re-planning took 0.63 s on average and 0.82 s at most per simulated hour, including 8 forecast
fetches; the budget is 5 s.

### Results on the offline game (synthetic grid, 4 seeds)

| Policy | Carbon | Energy | On time |
| --- | --- | --- | --- |
| naive (first legal zone, start at release) | 24.7 kg | 124.4 kWh | 15/15 |
| + cleanest zone | 14.0 kg | 107.1 kWh | 15/15 |
| + zone + time shift | 14.0 kg | 107.4 kWh | 15/15 |
| carbon-aware (blocks with stop/resume) | 13.3 kg | 108.5 kWh | 15/15 |

That is −46% against naive, mostly from *where*. These are synthetic numbers; the platform computes the
real greenops-score-v2.

### Assumptions to verify on the real API

Assumptions, checked only against the fake so far: active watts during boot, input, compute and output, and
idle watts while waiting or after done. Forecast points are hourly and aligned to whole hours. Instance-type
ids equal catalog profile ids, with a fallback to family + size. Stop and start return an operation whose
effect shows in the next work-status poll.

## Earlier synthetic path (kept: the Control Room and Earth view use it)

### What we knew before the event

`greenops/catalog.py` holds everything read off the organizers' challenge guide and platform preview:
the 15 workload IDs, names, CPU/GPU and allowed countries; 11 zones in 8 countries (AT, BG, CH, DE, ES, FR, HR, IT)
with their cities; GPU families and caps (GPU2, GPU3, RTX 3080 Ti, A30, A5000 at 8 cards, RTX 6000 Pro at 4);
20 VMs / 320 vCPUs; the platform's phase names. Numbers we could not see (durations, deadlines, zone IDs other than
`at-vie-1`, GPU memory, which zone has which GPU, power and throughput) are marked ASSUMED and get replaced from the
starter kit on Friday. Practice scenarios randomize only the assumed numbers, so we tune to the shape of the problem,
never to one scenario.

### What is here

| File | What it does |
| --- | --- |
| `greenops/catalog.py` | Known facts from the challenge guide and preview, and clearly marked assumptions |
| `greenops/experiments.py` | Experiment ladder: baseline, + cleanest zone, + forecast waiting, and an idle-VM ablation, on the same seeds |
| `greenops/model.py` | Zones, VM profiles, workloads, quotas, run state |
| `greenops/guard.py` | Residency guard. A placement in a forbidden country disqualifies the run, so every create goes through it twice |
| `greenops/policy.py` | `Baseline` (fixed legal zone, start at release) and `CarbonAware` (forecast-driven planner, re-planned every tick) |
| `greenops/sim.py` | Local stand-in for the platform: boot, setup, checkpoints, delivery, quotas, idle draw, residency DQ. **Score is a stand-in** |
| `greenops/scenario.py` | Random practice scenarios shaped like the challenge (15 workloads, 120 h, 11 zones, 8 countries) |
| `greenops/controller.py` | observe → decide → act loop, for the simulator and for the live platform |
| `greenops/exoscale_exec.py` | Executor for the real API (Exoscale Python binding). TODOs mark what we learn on Friday |
| `compare.py` | Runs both policies over N seeds and prints the averages |
| `tests/` | Residency rules, legal options, no-DQ full runs, carbon-aware beats baseline |

### Run

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 19 tests
python compare.py 20         # policy comparison on 20 practice scenarios
python -m greenops.experiments --seeds 12   # experiment ladder, one change at a time
```

Experiment ladder on 12 practice scenarios shaped like the real challenge (stand-in score):

| Step | Avg carbon | vs baseline | Energy | All on time |
| --- | --- | --- | --- | --- |
| Baseline (fixed legal zone, start at release) | 20.0 kg | – | 122.7 kWh | 12/12 |
| + cleanest zone now | 13.2 kg | −34% | 123.7 kWh | 12/12 |
| + wait for cleaner hours | 12.9 kg | −36% | 123.3 kWh | 12/12 |
| Ablation: keep idle VMs | 22.2 kg | +11% | 201.4 kWh | 12/12 |

Takeaway so far: *where* matters most, *when* adds a little, and deleting idle VMs is worth more than waiting.
Re-run on the real scenario once the platform is open; these are synthetic numbers.

### How the old policy decides

For each released workload that is not running yet, every tick:

1. List every **legal** option: allowed country × suitable VM profile × number of workers.
2. For each option, compute the latest safe start: `deadline − duration × 1.2 − 2 h`.
3. For every start hour from now to that latest start, estimate carbon from the **current** forecast
   (beyond 48 h: the forecast's last-day mean).
4. Start now if now is the best hour or waiting saves less than 3 %; otherwise wait and re-plan next tick.
5. Hand out quota to the jobs with the least slack first; fall back to the next option if quota is full.
6. Delete VMs the moment their job is delivered (idle VMs still count).
7. Skip a job that can no longer finish in time (switch: `run_hopeless`).

It only ever uses forecasts issued up to "now", never actual future values (challenge rule).
