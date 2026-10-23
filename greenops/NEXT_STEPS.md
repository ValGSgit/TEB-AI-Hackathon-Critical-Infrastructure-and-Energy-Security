# GreenOps: where we are and what comes next

Written after day 1 (Fri 23 Oct 2026). Start here on Saturday.

## Status

- The real-challenge orchestrator (`greenops/planner.py` + `greenops/live.py`) completed its **first practice
  run at 360×**. All 15 workloads were delivered on time, the run stayed qualified, every VM was deleted, and the
  platform refused no actions. It is **first on the preliminary leaderboard**. The carbon and score figures are on
  the run dashboard only; real-run values stay out of git (rule 2).
- Everything is on `main`: PRs #6 and #7. Tests: `python -m pytest -q` from `greenops/` (36 tests, about 50 s on Windows).
- Open PR #5 (Oliver, `docs/context/`). Once merged, update `architecture.md`, `workflow.md`, `decisions.md`
  (ADRs: rolling-horizon slot planner; vendored public spec) and `glossary.md` (stop/resume, block, run hours).

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
docker run --rm --read-only --tmpfs /tmp --cpus 2 --memory 1g --env-file .env \
  -v "$PWD/greenops-exo.json:/cfg/greenops-exo.json:ro" greenops --config /cfg/greenops-exo.json
```

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
  (no quota fit before its deadline). It finished only 1.9 h before its deadline. This is the main risk to the
  5,000-point on-time bonus.

## Plan, in order

1. **Stop the postponing** (`planner.py`, `_replan` / `_best_block`).
   - Commit to a job's start once it is within about 2 h, instead of re-optimizing it away.
   - Floor on spare time: never plan a block that leaves less than about 25% of the job's window as slack.
   - Keep quota headroom for the end of the run: plan the jobs that need the most quota earlier, or reserve
     capacity in the last 24–36 h.
   - Add an offline test in `tests/test_planner.py` that reproduces late crowding (track the minimum slack per
     job over a `play.run`).
2. **Never exit mid-run** (`live.py` main loop): catch every exception per iteration except
   `ResidencyViolation`, log it and continue. A crash leaves VMs unmanaged.
3. **Check carbon offline:** `python -m greenops.play --seeds 8` before and after each change; keep 15/15 on
   time.
4. **Second practice run at 720× in Docker** (judges' speed and Python version). Compare with run 1 on the
   dashboard. Finalize the better one.
5. **Created jobs can adapt** (planner):
   - Add workers up to `max_workers` when slack gets low (w-06 was stuck on 1 of 2).
   - Let a created job move its run hours later; stopping costs no electricity.
6. **Run analysis script:** read `decisions.jsonl` and `status.jsonl`, report planned vs actual starts, slack
   over time, run/stop hours and idle VMs. It also feeds the Control Room.
7. Ideas, if time allows: all legal zones instead of the top 2 per profile; stop extra workers once only output
   remains; use this run's own `carbon-intensity/history` to improve the estimate beyond 24 h.

## In parallel (colleague)

- Tests for residency (every workload against all 11 zones, an adversarial create that never reaches the API)
  and for the forecast/baseline accounting.
- Control Room UI (`ui/template.html`) fed from a run's `decisions.jsonl` / `status.jsonl`. Show a "Stopped"
  phase, the block and run-hours explainer, a residency panel and the data we use. Only synthetic sample data
  in git.

## Submission checklist (Sunday)

- [ ] GitHub repo access for the judges, plus the exact commit SHA.
- [ ] Finalized practice run ID.
- [ ] Docker build/run instructions (`greenops/README.md`, "Container").
- [ ] No credentials or real-run carbon values in git (`git ls-files | grep -i -E "exo.*json|\.env"`).
