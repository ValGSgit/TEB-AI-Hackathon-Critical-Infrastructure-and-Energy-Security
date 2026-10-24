# GreenOps: where we are and what comes next

Written after day 1 (Fri 23 Oct 2026), after two practice runs. Start here on Saturday.

## Status

- The real-challenge orchestrator (`greenops/planner.py` + `greenops/live.py`) completed its **first practice
  run at 360×**. All 15 workloads were delivered on time, the run stayed qualified, every VM was deleted, and the
  platform refused no actions. It is **first on the preliminary leaderboard**. The carbon and score figures are on
  the run dashboard only; real-run values stay out of git (rule 2).
- Everything is on `main`: PRs #6–#11 (#9: the controller never exits mid-run; #11: Oliver's residency/forecast
  tests and UI). Tests: `python -m pytest -q` from `greenops/` (86 tests, about 2 min).
- PR #5 (Oliver, `AGENTS.md` + `docs/context/`) is merged, with `docs/context/` updated for the real-challenge path
  (ADR-0007 to ADR-0010). Keep those docs current in the same commit as each change.

## How to run (practice)

From `greenops/`:

1. Create a fresh run on the portal and leave it READY. **Do not press "Start clock"**: our first VM create
   starts the clock.
2. Credentials are all git-ignored. The run's CLI config `greenops-exo.json` goes in the repo root. The grid
   secret goes in a root `.env` (`GRID_SECRET=...`; short names like `API_KEY` / `CLOUD_ENDPOINT` also work) or
   in `greenops/.local/greenops.env`. The template is `credentials.example.env`. Windows hides extensions:
   check that the file is not `greenops-exo.json.json`.
3. `python -m greenops.live --probe --out .local/probe`: read-only, creates nothing. It checks zones and
   instance types and the forecast shape, and prints the plan it would make with every zone residency-checked.
4. `python -m greenops.live --out .local/runN`: the run. Logs go to `decisions.jsonl` and `status.jsonl` in that
   folder. If the process dies, start it again: it adopts the existing VMs.
5. Afterwards, note the dashboard's carbon and score for the run ID somewhere local, never in git. Finalize the
   best run on the portal and rotate the keys. At most two unfinished practice runs per team.

On Windows, set `PYTHONUTF8=1` (the exoscale package reads its spec with the default encoding). Prefer running
in our Docker image (Python 3.13, what the judges use):

```bash
docker build -t greenops greenops
mkdir -p greenops/.local/runN
docker run --rm --read-only --tmpfs /tmp --cpus 2 --memory 1g --env-file .env \
  -v "$PWD/greenops-exo.json:/cfg/greenops-exo.json:ro" -v "$PWD/greenops/.local/runN:/tmp/out" \
  greenops --config /cfg/greenops-exo.json --out /tmp/out
```

Add `--probe` first for the read-only check. Without the `/tmp/out` mount the logs vanish with the container.
In Git Bash on Windows, prefix with `MSYS_NO_PATHCONV=1` and use `$(pwd -W)` instead of `$PWD`.

`--env-file .env` works with the short names too; `live.py` maps them to the full ones.

Git push: the `origin` remote uses SSH with a passphrase. Without a prompt:
`git -c credential.helper='!gh auth git-credential' push https://github.com/ValGSgit/TEB-AI-Hackathon-Critical-Infrastructure-and-Energy-Security.git <branch>`

## What run 1 taught us

- Verified on the real API: zones and instance-type ids equal the catalog, forecasts are hourly from T0 (6 or 24
  points, `datetime` + `carbonIntensity`), the work status matches the spec's required work for all 15
  workloads, and the first create starts the clock.
- **Bug, fixed:** the work status sends timestamps like `…40.91+00:00`, which Python < 3.11 rejects. The
  controller crashed at simulated hour 68 and was restarted at hour 71, when it adopted the 5 workloads that
  still had VMs. `spec.to_h` now accepts any fraction length.
- **Postponing:** each hourly re-plan could push a start later (w-06: planned hour 34, created 56; w-15: 37 → 74;
  w-14: 61 → 79). Jobs ended up with zero slack, and at hours 77 and 80 `w-05-eu-render` was briefly "blocked"
  (no quota fit before its deadline). It finished only 2.0 h before its deadline (`succeeded_at` in
  `.local/run1/status.jsonl:115`). This is the main risk to the 5,000-point on-time bonus.

## Run 2 (720×, in our Docker image: the judges' setup)

- Same planner as run 1, plus the fixes from #7 and #9. It ran in the container with a read-only root, 2 CPUs and
  1 GiB, credentials from `--env-file .env`, and logs mounted to `greenops/.local/run2`.
- 15/15 delivered on time, all 15 VMs deleted, the controller ended on its own at simulated hour 117.7. No crash,
  no warnings, no refused actions. Compare its score with run 1 on the dashboard and finalize the better one.
- The same weak spot as run 1: `w-05-eu-render` was "blocked" at hours 77 and 80 and finished 1.9 h before its
  deadline (`.local/run2/status.jsonl:118`). The postponing is systematic, not bad luck, so plan item 1 is the
  priority.
- All run figures in this file come from `python -m greenops.analyze .local/run1 .local/run2`, which cites the
  log line behind each one. Carbon and score are only on the dashboard (by run ID), never in git.

## Run 3 (720×, Docker, commit `e509df8`: slack_h + commit_h): a regression

- Same grid as runs 1 and 2 (the AT forecast at hour 0 is identical; `rules.json` pins the scenario).
- **14/15: `w-05-eu-render` never ran**, so the 5,000-point completion bonus was missed. It was planned for
  hour 88, then 96, was "blocked" from hour 65 and found no slot from hour 79 to the end
  (`.local/run3/decisions.jsonl:72–94`; after 79 the log is silent because it only logs state changes).
  Cause: nothing stopped a job from starving. Its spare time was judged on its maximum of 10 workers, so it
  looked flexible and was planned last. Created jobs and kept starts reserved their whole blocks first,
  and w-13/w-15 (2 workers each) took the late vCPU quota. Reproduced offline: with 240 instead of 320
  vCPUs, w-05 starves on every synthetic seed. The 4 h buffer did not prevent this.
- **The controller stalled.** Only 72 hourly status samples (run 2: 118). Hours 80–82, 86–87, 92, 94–95
  and 98 have none: up to ~4.7 simulated hours (~23 wall s) without a poll. In those gaps nothing happens.
  Deliveries were noticed late, and VMs idled for hours after delivery (w-12: delivered 97.2, our delete
  99.8, the platform's 102.1). The logs had no wall-clock timings, so the cause is not known yet.
- Otherwise: 0 refused actions, qualified, and the other 14 jobs were on time (`python -m greenops.analyze
  .local/run1 .local/run2 .local/run3`). A duplicate `create` line at t=0 is a log duplicate (one VM only).

## Run 4 (720×, Docker, commit `dc92006`: rescue pass + fast loop): 15/15

- Same grid as runs 1–3 (hour-0 AT forecast identical). 15/15 on time, qualified, 0 blocked, 0 refused.
- w-05 was created at hour 36 and finished 22 h early (run 3: never ran; runs 1/2: about 2 h early). The
  tightest job finished 5.2 h early, the best of all runs; no job finished less than 4 h early.
- **The platform was slow.** The work-status reply took 10.6 s at the median in slow polls (max 20 s), and
  one action took 21 s. 26 polls failed on our 10 s read timeout. Planning never took more than 0.23 s.
  Only 42 hourly samples. VMs idled 20.4 h in total after delivery (run 2: 2.2 h), because we learn about a
  delivery only from a status reply. Fix in item 0: a 30 s status timeout and a short retry.
- **Lower score than run 2** (dashboard, values in `.local/run{2,4}/platform_score.txt`), all from electricity.
  Cause: spare time was judged on 1 worker, so the parallel jobs (w-14, w-13, w-05, up to 6/4/10 workers) were
  planned first and created 40–60 h earlier than in run 2. They took the early quota, and others were squeezed:
  w-04 on a 16-vCPU machine with no room to pause (91 of 91 hours), w-11 with no pauses, w-09 on the slower GPU
  (43 h instead of 21.5 h). Fix (fix/urgent-when-late): judge spare time on `max_workers` again (run 2's order),
  and also mark a job urgent when its only slot ends past its soft end. Offline at 240 vCPUs: 15/15 on every
  seed, less carbon than with 1 worker; at 320 vCPUs unchanged (22,010, 13.35 kg).

## Run 5 (720×, Docker, commit `8e7d0bb`: run 2's order + rescue + late rule): 14/15

- Same grid. **w-03-med-analysis missed its deadline** (87.9%), so no completion bonus (dashboard values in
  `.local/run5/platform_score.txt`). Electricity was close to run 2's.
- Cause: platform latency, not planning. Status replies took 12.2 s at the median, so the controller saw the
  platform only every ~3 simulated hours. At hour 103.59 one reply took 65 s and the next action another 9 s.
  w-03 had been stopped at H93.4 with ~6 run hours left; our start reached the platform at H116.6, after the
  114 h deadline. The run also ended during that stall with five jobs' VMs not yet deleted
  (409 "run finished").
- Fix (fix/latency-guard, ADR-0015): `finish_h=12`. A created job with ≤ 12 run hours left runs them
  without pauses. Offline, decisions every 3 h with a 15 h stall at hour 103: 1/12 → 12/12 grids fully on
  time. Normal platform: −54 points (0.25%). Tried and rejected: adding the observed poll gap to every
  deadline margin. It shrank every job's window, brought crowding back and made stalls worse.
- Before run 6: an adverse-condition sweep (192 offline runs: polls every 0.25/1/3 h, 6–18 h stalls, 280 vCPUs,
  15% refused actions) found 0 exceptions and no misses on a normal platform. Added `flat_slack_h=12`: a created
  job with ≤ 12 h of spare time stops pausing (fewer misses after stalls, −9 points normally).
- Also fixed: a block for a created job could run past hour 120 and crash planning with an IndexError,
  which live would fail every poll. Never seen live; found by the stall test.

## Run 6 (720×, Docker, commit `2eb3677`): 12/15 in our logs, the slowest platform yet

- Status replies took 20 s at the median (max 36 s), so there was a decision only every 3–6 simulated hours. From
  hour 90 to 101 there was no reply (36 s status + 17.6 s action). At 101 the forecast requests timed out
  (20 s), **planning failed, and the controller did nothing**; the next status also timed out and the run ended.
- w-11 had been paused at hour 90 with 13 h of spare time (the rule was 12 h) and stayed stopped: missed.
  w-05 and w-13 were still running at hour 101 (1233/1440 and 1154/1440); our logs end there, so check
  the dashboard for whether they delivered.
- Fixes (fix/never-idle-when-blind, ADR-0016):
  - a failed forecast request reuses this run's latest forecast for that area, shifted to the current hour,
    and an area that failed in this hour's prefetch is not fetched a second time;
  - if planning still fails, safe mode starts every stopped VM of an unfinished workload;
  - the pause threshold grows with the platform's slowness: a created job stops pausing when its spare time
    is at most max(12 h, 3 × the longest gap between status replies seen).

## Plan, in order

0. **Before the next run (fix/no-starvation):**
   - Done, rescue pass (ADR-0013): a job left without a slot becomes urgent. It is planned right after
     created jobs until it is created. If it still has no slot, created jobs are planned flat out. Spare
     time is judged on 1 worker. Offline with 240 vCPUs: 13.0 → 15.0/15 on 6 seeds. With 320: unchanged.
     Test: `test_no_job_starves_when_quota_is_tight`.
   - Done, faster loop (ADR-0014): forecasts are fetched once per re-plan (the rescue pass re-plans up to
     3 times an hour) and cached per area and hour. The 8 areas are fetched in parallel at the hour boundary.
     Delivered VMs are deleted before anything else in the poll. Against the fake platform with 0.3 s per
     forecast request, a full run takes 27.9 s of wall time instead of 159.6 s (same 15/15).
   - Done, flat-out mode only for a starved job that can still finish at its fastest. Otherwise every
     created job would skip its pauses for nothing.
   - Done, slow-poll logging: any poll over 2 s prints `slow_poll_s` with the status/plan/act split to the
     console. Read `console.log` after run 4.
   - Checked, no change: all legal zones instead of the top 2 per profile (16 seeds: identical score and
     carbon, planning 2.4× slower).
   - Run 4: done (above).
   - Status timeout: wait up to 30 s for the work status (it took 10–20 s in run 4) and retry after 0.5 s
     instead of failing at 10 s and sleeping 2 s.

1. **Stop the postponing** (`planner.py`, `_replan`): done offline; live, run 3 shows it is not enough on its own.
   - Done, `slack_h=4`: each job is planned to end 4 h before its latest end when that fits. A created job
     that no longer fits that runs every hour instead of pausing. This is where the gain comes from: created
     jobs stopped drifting to the deadline.
   - Done, `commit_h=2`: a start planned within 2 h is kept (same placement and hour) and gets quota right
     after the created jobs. Offline it changes almost nothing; it is there for the real-run start drift
     (w-15: 37 → 74). Not a measured win.
   - Offline, 32 seeds, old → new: mean slack of the tightest job 2.5 → 6.3 h, score −7 points (0.03%),
     carbon +0.2%, 15/15 on time, no "blocked". Tried instead: 5% of the window and a 6 h buffer gave an
     uneven worst case; 7–15% of the window and an 8 h buffer brought "blocked" back. Tests: seeds 11/12
     need ≥ 5 h slack on every job and no "blocked".
   - Quota crowding (seed 14 offline, w-05 in run 3 live) is handled by the rescue pass in item 0.
2. ~~Never exit mid-run~~: done in #9. Every error except `ResidencyViolation` is logged and retried on the
   next poll.
3. **Check carbon offline:** `python -m greenops.play --seeds 8` before and after each change; keep 15/15 on
   time.
4. ~~Practice runs at 720× in Docker~~: runs 2 and 3 (above). Next: run 4 after item 0.
5. **Created jobs can adapt** (planner):
   - Add workers up to `max_workers` when slack gets low (w-06 was stuck on 1 of 2).
   - Let a created job move its run hours later; stopping costs no electricity.
6. ~~Run analysis script~~: done, `python -m greenops.analyze .local/runN [--json]`. Per job: delivery vs
   deadline, first planned start vs create, zone and workers, blocked/refused, idle after delivery; each with
   its log line. Still to do: slack over time, run/stop hours, and feeding the Control Room.
7. Ideas, if time allows: all legal zones instead of the top 2 per profile; stop extra workers once only output
   remains; use this run's own `carbon-intensity/history` to improve the estimate beyond 24 h.

## In parallel (colleague)

Done in #11 (ported from Oliver's `feature/hardening-tasks`, fixed to run on main): `tests/test_residency.py`,
`tests/test_forecast.py`, and the Control Room's "Data we use", scheduler explainer, residency panel and filterable
decision feed. Still open: load a real run's `decisions.jsonl` / `status.jsonl` (kept out of git).

- Tests for residency (every workload against all 11 zones, an adversarial create that never reaches the API)
  and for the forecast/baseline accounting.
- Control Room UI (`ui/template.html`) fed from a run's `decisions.jsonl` / `status.jsonl` (`analyze.py --json`
  is a start). Until then its numbers come from the pre-event synthetic model and old policy (assumed
  catalog, 48 h forecasts, 3% rule): do not use them as evidence in the pitch. Show a "Stopped"
  phase, the block and run-hours explainer, a residency panel and the data we use. Only synthetic sample data
  in git.

## Submission checklist (Sunday)

- [ ] GitHub repo access for the judges, plus the exact commit SHA.
- [ ] Finalized practice run ID.
- [ ] Docker build/run instructions (`greenops/README.md`, "Container").
- [ ] No credentials or real-run carbon values in git (`git ls-files | grep -i -E "exo.*json|\.env"`).
