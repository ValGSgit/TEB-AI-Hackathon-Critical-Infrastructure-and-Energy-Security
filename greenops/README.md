# GreenOps scheduler (pre-build for the Exoscale GreenOps Challenge)

Carbon-aware orchestrator for the TEB Critical Infrastructure Hackathon, 23–25 Oct 2026.
Built before the event against **synthetic practice scenarios**; the organizers' data,
API details and scoring formula are plugged in on Friday.

## What is here

| File | What it does |
| --- | --- |
| `greenops/model.py` | Zones, VM profiles, workloads, quotas, run state |
| `greenops/guard.py` | Residency guard. A placement in a forbidden country disqualifies the run, so every create goes through it twice |
| `greenops/policy.py` | `Baseline` (fixed legal zone, start at release) and `CarbonAware` (forecast-driven planner, re-planned every tick) |
| `greenops/sim.py` | Local stand-in for the platform: boot, setup, checkpoints, delivery, quotas, idle draw, residency DQ. **Score is a stand-in** |
| `greenops/scenario.py` | Random practice scenarios shaped like the challenge (15 workloads, 120 h, 11 zones, 8 countries) |
| `greenops/controller.py` | observe → decide → act loop, for the simulator and for the live platform |
| `greenops/exoscale_exec.py` | Executor for the real API (Exoscale Python binding). TODOs mark what we learn on Friday |
| `compare.py` | Runs both policies over N seeds and prints the averages |
| `tests/` | Residency rules, legal options, no-DQ full runs, carbon-aware beats baseline |

## Run

```bash
pip install -r requirements.txt
python -m pytest -q          # 19 tests
python compare.py 20         # policy comparison on 20 practice scenarios
```

Result on 20 practice scenarios (stand-in scoring):

| Policy | Avg score | Avg carbon | Jobs delivered | All-done bonus |
| --- | --- | --- | --- | --- |
| Baseline | 20,223 | 15.9 kg | 14.9 / 15 | 19 / 20 |
| Carbon-aware | 23,227 | 4.3 kg | 14.9 / 15 | 19 / 20 |

The one miss is a job that no option could finish before its deadline.

## How the carbon-aware policy decides

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

## Friday checklist

1. Confirm with the organizers that code written before the event is allowed (generic algorithm work; no scenario knowledge).
2. Write `greenops/loaders.py`: map the workload definitions, resource catalog and zone list to `model.py`.
3. Fill the TODOs in `exoscale_exec.py`: user-data format, work-status API, instance-type naming, template ID, run clock.
4. Replace `Sim.score()` with the frozen scoring policy, then re-tune `safety`, `buffer_h`, `min_gain`.
5. Practice run with the starter kit's two fixed workloads, then the full controller.

## Next improvements, in order

- Pause and resume checkpointable jobs through dirty hours when the saving beats the extra setup.
- Move checkpointable jobs between zones when a forecast shift is large and lasting.
- Reserve quota ahead for jobs whose cleanest window is later, so a tight job is never blocked.
- Choose worker count by marginal carbon per unit of work, not only duration.

Credentials come from `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET`; never commit them.
