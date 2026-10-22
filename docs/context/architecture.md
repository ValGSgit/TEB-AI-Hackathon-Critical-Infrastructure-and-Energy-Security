# Architecture

Repo: TEB AI Hackathon team repo (weXelerate, Vienna, 23–25 Oct 2026). Team of three. Everything built before and
during the event lives here.

## Top level

| Path | Contents |
| --- | --- |
| `README.md` | Hackathon framing, repo map (both tracks), quick start, working rules, open questions |
| `docs/` | `challenge-choice-and-prebuild.md` (organizer challenges, decision, pre-build status, Friday checklist) |
| `greenops/` | Primary track: Exoscale Carbon-Aware Cloud Orchestration |
| `forcegeo/` | Security track (backup): ForceGeo location-trust and Galileo integrity demos |
| `.github/workflows/tests.yml` | CI: greenops tests, galileo-live build, greenops export/UI/globe build |
| `AGENTS.md`, `CLAUDE.md`, `.gitignore` | Agent instructions (CLAUDE.md imports AGENTS.md) and ignore rules |

## greenops/ (primary track)

Product area that contains the scheduler, the decision-explainer UI and the 3D replay. The Python package is
`greenops/greenops/`; scripts, tests and pages sit directly under `greenops/`. Layered as:

1. `greenops/greenops/catalog.py` — known facts from the organizers' guide/preview vs. clearly marked ASSUMED values.
2. `greenops/greenops/scenario.py` — synthetic practice scenarios shaped like the real challenge (random per seed).
3. `greenops/greenops/model.py` — normalized domain objects (Zone, Profile, Workload, Quotas, RunState).
4. `greenops/greenops/guard.py` — residency guard (forbidden country -> run disqualified).
5. `greenops/greenops/policy.py` — `Baseline` and `CarbonAware` planners + `apply` (decide/act bridge).
6. `greenops/greenops/sim.py` — local stand-in platform (boot/setup/running/delivering/done, quotas, idle draw, DQ) and
   stand-in scoring.
7. `greenops/greenops/controller.py` — observe -> decide -> act loop (sim and live executor).
8. `greenops/greenops/exoscale_exec.py` — executor scaffold for the real Exoscale API (TODOs for Friday).
9. `greenops/greenops/experiments.py` — experiment ladder (one policy change at a time, same seeds).
10. `greenops/greenops/export.py` — run export as JSON consumed by the UI/globe (data contract `schema: 1`).
11. `greenops/compare.py` — baseline vs carbon-aware over N seeds.
12. `greenops/tests/` — pytest suite (guard, export, experiments).
13. `greenops/ui/` — Control Room dashboard (static page built from `template.html` + `data/run.json` + `data/experiments.json`).
14. `greenops/globe/` — GreenOps Earth 3D replay (built from `template.html` + run JSON + shared orbit data).
15. `greenops/Dockerfile`, `greenops/pytest.ini`, `greenops/requirements.txt`.

## forcegeo/ (security track)

Standalone demo area, kept separate from the GreenOps product:

| Path | What it is |
| --- | --- |
| `showcase/` | Interactive demo page: location-trust checks for pipeline commands on the real TAG/SOL gas corridor. Backup for the open security track. |
| `galileo-live/` | Demo page with live Galileo and Sentinel-2 positions from real orbit data (TLE). `build.py` regenerates `galileo-live.html` from `template.html` + `data/` (CelesTrak TLEs, Natural Earth world). |
| `galileo-design/` | Source of two design-canvas screens: authentic Galileo sky vs. replay spoofing attack at the Murfeld sensor (they need the canvas runtime, see known-issues). `compute_sky.py` computes the real sky with skyfield -> `sky2.json`. |

## Cross-cutting concerns

- Policy pattern: planners return a list of actions (`create`/`delete`); the controller applies them.
- Challenge rule enforced in code: a policy only sees forecasts issued up to now; no scenario-specific future values.
- Residency: every create passes through `check_placement` in `greenops/greenops/guard.py` (and the executor re-checks right before the API call).
- Data flow into the UI (from `greenops/`): `python -m greenops.export` -> `ui/data/run.json` -> `ui/build.py` ->
  `ui/dashboard.html`; `python -m greenops.experiments` -> `ui/data/experiments.json` -> `ui/build.py`. The same run JSON
  feeds `globe/build.py`. Pages are generated: edit `template.html`, not the built HTML.
