# GreenOps: where we are and what comes next

Written after day 1 (Fri 23 Oct 2026), after two practice runs. Start here on Saturday.

## Status

- The real-challenge orchestrator (`greenops/planner.py` + `greenops/live.py`) completed its **first practice
  run at 360×**. All 15 workloads were delivered on time, the run stayed qualified, every VM was deleted, and the
  platform refused no actions. It is **first on the preliminary leaderboard**. The carbon and score figures are on
  the run dashboard only; real-run values stay out of git (rule 2).
- Everything is on `main`: PRs #6–#11 (#9: the controller never exits mid-run; #11: Oliver's residency/forecast
  tests and UI). Tests: `python -m pytest -q` from `greenops/` (75 tests, about 2 min).
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

## Plan, in order

1. **Stop the postponing** (`planner.py`, `_replan`): mostly done, not yet tried live.
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
   - Open: seed 14 still delivers w-05 only 2.3 h early. It is created at hour 70 on 1 worker because quota
     for 2 workers is taken. That is quota crowding: plan the jobs that need the most quota earlier, or
     reserve capacity in the last 24–36 h.
2. ~~Never exit mid-run~~: done in #9. Every error except `ResidencyViolation` is logged and retried on the
   next poll.
3. **Check carbon offline:** `python -m greenops.play --seeds 8` before and after each change; keep 15/15 on
   time.
4. ~~Second practice run at 720× in Docker~~: done (run 2, above). After item 1, do run 3 the same way and
   compare on the dashboard.
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
