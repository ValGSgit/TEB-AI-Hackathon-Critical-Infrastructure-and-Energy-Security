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
| `greenops/analyze.py` | Reads a live run's own logs: delivery vs deadline per job, planned vs actual start, blocked/refused actions, idle time; cites the log line behind every number |
| `tests/fake_platform.py` | HTTP fake of the API subset `live.py` uses, served over the offline game |

### How the planner decides

- Cost of running a workload in hour *t* = kW (profile × workers) × zone PUE × estimated g/kWh. Inside
  the 24-hour forecast the estimate is the forecast. Beyond it, it is a 50/50 blend of the same hour's
  forecast value and the forecast mean, plus a 10% risk premium, so known clean hours beat guesses.
- Stopped VMs keep their quota. Each job therefore gets a **block** [start, start+L), with L between 1× and
  2× its run time. Its **run hours** are the cleanest hours inside the block, and the job is stopped in the
  others. Quota (vCPUs, GPU cards, VM count) is reserved for the whole block.
- Jobs are planned least flexible first, already-created ones first. Placement (zone, profile, workers) is
  chosen among residency-legal zones only, with faster worker counts as fallbacks. Every job must finish
  2 h before its deadline (`margin_h`) and is planned to finish 4 h before that when it fits (`slack_h`).
  A created job that no longer fits that runs every hour instead of pausing.
- A start planned within 2 h is kept (`commit_h`): same placement and hour, quota right after created jobs.
- Actions each tick: delete (after `final_output_delivered`), stop, start, create. The first create runs
  while the run is READY, because the run clock starts at the first accepted create. A refused action is
  forgotten and re-planned. Every change goes to a decision log with its reason.

### Run

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 97 tests (on Windows: set PYTHONUTF8=1 for the exoscale package)
python -m greenops.play --seeds 4         # policy comparison on the offline game
python -m greenops.live --probe --out .local/probe     # read-only API checks, creates nothing
python -m greenops.live --out .local/run1              # live run
python -m greenops.analyze .local/run1                 # what the run did, from its own logs
```

Credentials never go in git: `.local/greenops.env` (template: `credentials.example.env`), the run's CLI
config `greenops-exo.json` (both git-ignored), or the environment:
`EXOSCALE_API_KEY`, `EXOSCALE_API_SECRET`, `GREENOPS_CLOUD_ENDPOINT`, plus `GREENOPS_GRID_ENDPOINT` and
`GREENOPS_GRID_SECRET`. The loop writes `decisions.jsonl` and `status.jsonl` to `--out`
(default `/tmp/greenops-run`).

### First practice run

1. Create a practice run on the platform. Leave it READY: nothing should create a VM yet, because the
   first accepted create starts the clock.
2. Put the run's downloaded `greenops-exo-<run-id>.json` in the repo root (git-ignored; found
   automatically). Then `cp credentials.example.env .local/greenops.env` and set `GREENOPS_GRID_SECRET`, the
   separate grid secret from the portal's API credentials page. The grid URL is derived from the cloud
   endpoint. `.local/` is git-ignored, and `live.py` reads that file automatically.
3. `python -m greenops.live --probe --out .local/probe` runs read-only checks and creates nothing. It prints
   whether zones and instance-type ids match the catalog, the run state and speed, the work-status fields
   and the forecast shape. The raw responses go to `.local/probe/probe.json`; that is run data, so keep it
   out of git.
4. `python -m greenops.live --out .local/run1` runs the planner. It creates the first VM while the run is
   READY, then re-plans every simulated hour until the run ends. Watch the platform dashboard alongside.
   Practice runs can be paused or change speed, so there is no wall-clock limit unless `--max-wall` is given.

At most two unfinished practice runs per team. Judging is a fresh run at 720×.

### Container (what the judges run)

Planner profile: `GREENOPS_PLANNER` (`default`, the judged configuration, or `run2plus`; ADR-0017).

```bash
docker build -t greenops greenops
docker run --rm --read-only --tmpfs /tmp --cpus 2 --memory 1g   -e EXOSCALE_API_KEY -e EXOSCALE_API_SECRET -e GREENOPS_CLOUD_ENDPOINT   -e GREENOPS_GRID_ENDPOINT -e GREENOPS_GRID_SECRET greenops
```

The image is `python:3.13-slim` with pinned `exoscale==0.16.3`, `requests==2.34.2` and `numpy==2.2.6`. It runs
as a non-root user and writes only to `/tmp`. A full 120-hour run against the fake platform inside the
container, with these limits (1 s polling = 0.2 simulated hours at 720×), delivered 15/15 at 53 MiB peak
memory. Re-planning took 0.63 s on average and 0.82 s at most per simulated hour, including 8 forecast
fetches; the budget is 5 s. (Measured once, 23 Oct, commit `b695511`, before the slack/commit rules.)

### Results on the offline game (synthetic grids, 8 seeds: `python -m greenops.play --seeds 8`)

| Policy | Carbon (mean ± sd) | Energy | Score | On time |
| --- | --- | --- | --- | --- |
| naive (first legal zone, fastest profile, start at release) | 24.63 ± 0.77 kg | 124.4 kWh | 20,323 | 15/15 |
| + cleanest zone and efficient hardware | 14.12 ± 0.43 kg | 106.7 kWh | 21,886 | 15/15 |
| + time shift | 14.07 ± 0.43 kg | 107.3 kWh | 21,894 | 15/15 |
| carbon-aware (blocks with stop/resume) | 13.73 ± 0.44 kg | 108.1 kWh | 21,945 | 15/15 |

That is −44% against naive, mostly from *where* and *which hardware*. These are synthetic grids. `game.score()`
uses the greenops-score-v2 formula (see the root README), which we confirmed against the platform's
per-workload breakdown.

### Assumptions checked on the real API

Confirmed by the read-only probe (`.local/probe/probe.json`) and practice runs 1 and 2: the 11 zones equal
the catalog; instance-type ids equal catalog profile ids; forecasts are hourly from T0 with 6 or 24 points
(`datetime`, `carbonIntensity`); the work status carries the spec's required work for all 15 workloads;
the first accepted create starts the clock; stop and start show up in the next work-status poll (both
runs: 15/15 delivered, 0 refused actions, per `python -m greenops.analyze`).

Still unverified (the API does not expose it): the power draw per phase (boot, input, compute, output,
idle). The offline game models it from the catalog; only the dashboard's carbon reflects the real values.

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
python -m pytest -q          # the full suite (97 tests, both paths)
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
