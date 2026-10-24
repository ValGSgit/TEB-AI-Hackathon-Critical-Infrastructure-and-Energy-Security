# Architecture

Repo: TEB AI Hackathon team repo (weXelerate, Vienna, 23–25 Oct 2026). Team of three. Everything built before and
during the event lives here.

## Top level

| Path | Contents |
| --- | --- |
| `README.md` | The submission: problem, approach, results, architecture, how to run, repo map |
| `docs/` | `greenops-challenge-brief.txt` (the organizers' challenge text), `context/` (these files) |
| `greenops/` | Primary track: Exoscale Carbon-Aware Cloud Orchestration |
| `forcegeo/` | Security track (backup): ForceGeo location-trust and Galileo integrity demos |
| `site/` | Project site: `template.html` + `build.py` (replay data from the offline game on synthetic grids); copies the Control Room and Earth view in. Published by `.github/workflows/pages.yml` |
| `.github/workflows/tests.yml` | CI: greenops tests (Python 3.12 and 3.13), judged image build, galileo-live build, greenops export/UI/globe build |
| `.gitignore` | Ignore rules: credentials, run logs, local clones |

## greenops/ (primary track)

Product area that contains the scheduler, the decision-explainer UI and the 3D replay. It has two paths.

### Real-challenge path (what the judges run)

| Path | Role |
| --- | --- |
| `greenops/challenge/` | Public spec vendored from the organizers' starter kit (`catalog`, `workloads`, `rules`, `manifest` JSON); SHA-256 checked on load |
| `greenops/greenops/spec.py` | Loads the spec into the model: zones/sites, 22 profiles (GPU tflop/s converted to per hour), 15 workloads with resolved residency, quotas, frozen score constants; time = hours since 2025-09-30T00:00Z |
| `greenops/greenops/planner.py` | Rolling-horizon slot planner (re-plans every simulated hour): blocks, run hours, quota reservation, placement among legal zones; `bootstrap` starts the clock, `_adopt` takes over existing VMs, decision log with reasons. Named profiles (`GREENOPS_PLANNER`): `adaptive` (default, judged), `safe`, `run2plus` |
| `greenops/greenops/live.py` | Entry point `python -m greenops.live`: run-scoped clients for cloud (EXO2 via the `exoscale` binding), grid forecasts (`auth-token`) and signed work status; rate limiter; `--probe` read-only check; never exits mid-run except on a residency violation |
| `greenops/greenops/game.py` | Offline game with the published rules (stop/resume, sync overhead, input per worker, idle until delete) on a synthetic practice grid; approximate v2 score |
| `greenops/greenops/play.py` | `python -m greenops.play`: naive vs +zone vs +shift vs carbon-aware on the offline game |
| `greenops/greenops/export_game.py` | `python -m greenops.export_game`: the real-challenge path (spec, planner, naive baseline, offline game) as the Control Room / Earth view JSON (schema 1) |
| `greenops/greenops/analyze.py` | `python -m greenops.analyze .local/runN`: what a live run did, from its own logs, with the log line behind every number |
| `greenops/tests/fake_platform.py` | HTTP fake of the API subset over `game.py`, used to test `live.py` end to end |
| `greenops/Dockerfile` | Judged image: Python 3.13, unprivileged, read-only root, writes only `/tmp`; `ENTRYPOINT python -m greenops.live` |

### Earlier synthetic path (kept for the Control Room and Earth view)

Not judged. The Python package is `greenops/greenops/`; scripts, tests and pages sit directly under `greenops/`. Paths below are relative to the
repo root. Layered as:

1. `greenops/greenops/catalog.py` — known facts from the organizers' guide/preview vs. clearly marked ASSUMED values.
2. `greenops/greenops/scenario.py` — synthetic practice scenarios shaped like the real challenge (random per seed).
3. `greenops/greenops/model.py` — normalized domain objects (Zone, Profile, Workload, Quotas, RunState).
4. `greenops/greenops/guard.py` — residency guard (forbidden country -> run disqualified).
5. `greenops/greenops/policy.py` — `Baseline` and `CarbonAware` planners + `apply` (decide/act bridge).
6. `greenops/greenops/sim.py` — local stand-in platform (boot/setup/running/delivering/done, quotas, idle draw, DQ) and
   stand-in scoring.
7. `greenops/greenops/controller.py` — observe -> decide -> act loop (sim and live executor).
8. `greenops/greenops/exoscale_exec.py` — pre-event scaffold, superseded by `live.py`; kept only for reference.
9. `greenops/greenops/experiments.py` — experiment ladder (one policy change at a time, same seeds).
10. `greenops/greenops/export.py` — run export as JSON consumed by the UI/globe (data contract `schema: 1`).
11. `greenops/compare.py` — baseline vs carbon-aware over N seeds.
12. `greenops/tests/` — pytest suite for both paths (guard, residency, spec, planner, forecast, live, export, experiments).
13. `greenops/ui/` — Control Room dashboard (static page built from `template.html` + `data/run.json` + `data/experiments.json`).
14. `greenops/globe/` — GreenOps Earth 3D replay (built from `template.html` + run JSON + shared orbit data).
15. `greenops/Dockerfile`, `greenops/pytest.ini`, `greenops/requirements.txt`.

## forcegeo/ (security track)

Standalone demo area, kept separate from the GreenOps product:

| Path | What it is |
| --- | --- |
| `showcase/` | Interactive demo page: location-trust checks for pipeline commands on the real TAG/SOL gas corridor. Backup for the open security track. |
| `galileo-live/` | Demo page with live Galileo and Sentinel-2 positions from real orbit data (TLE). `build.py` regenerates `galileo-live.html` from `template.html` + `data/` (CelesTrak TLEs, Natural Earth world). |
| `galileo-design/` | Source of two design-canvas screens: authentic Galileo sky vs. replay spoofing attack at the Murfeld sensor (view them in the published design canvas; they need the canvas runtime, see known-issues). `compute_sky.py` computes the real sky with skyfield -> `sky2.json`. |

## Cross-cutting concerns

- Policy pattern: planners return a list of actions (`create`/`stop`/`start`/`delete`); the game driver
  (`play.apply`) or the live loop applies them. Refused actions go back through `Planner.rejected`.
- Challenge rule enforced in code: a policy only sees forecasts issued up to now; no scenario-specific future values.
- Residency: every create passes through `check_placement` in `greenops/greenops/guard.py`, in the planner and again in
  `Live.create` before any HTTP call. `resolve_residency` turns ANYWHERE/EU/country + allow/forbid lists into a country set.
- Data flow into the UI (from `greenops/`): `python -m greenops.export` -> `ui/data/run.json` -> `ui/build.py` ->
  `ui/dashboard.html`; `python -m greenops.experiments` -> `ui/data/experiments.json` -> `ui/build.py`. The same run JSON
  feeds `globe/build.py`. Pages are generated: edit `template.html`, not the built HTML.
