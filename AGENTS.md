# AGENTS.md

Instructions for every coding assistant working in this repo (Claude, Codex, Cursor, opencode, ...). Three people
share the repo and each one uses a different tool, so nothing here may depend on a tool-specific feature.

## Hard rules (read first)

1. **Residency.** Never place a GreenOps workload in a country outside its allowed list. Every placement goes
   through `greenops/greenops/guard.py`; do not bypass or weaken it. A single forbidden attempt disqualifies the
   whole run, even if the platform rejects it.
2. **Forecasts only.** The scheduler may use only the electricity forecasts published for the current run. Never
   commit actual or future carbon values for a scenario, or a schedule built from them.
3. **No credentials in git.** Keys come from the environment (`EXOSCALE_API_KEY`, `EXOSCALE_API_SECRET`,
   `GREENOPS_GRID_SECRET`, ...) or from git-ignored files (`greenops-exo.json`, `.env`, `greenops/.local/`).
4. **Don't overwrite existing work.** Read the code and `docs/context/` before changing structure; extend, don't replace.

## Repo facts

- Python packages live under `greenops/greenops/`. Real-challenge path: `spec.py` (vendored spec in
  `greenops/challenge/`), `planner.py`, `live.py` (entry point), `game.py` / `play.py` (offline game). Earlier
  synthetic path: `policy.py`, `sim.py`, `export.py`. Tests in `greenops/tests/`; built pages in `greenops/ui/` and
  `greenops/globe/`. Status and plan: `greenops/NEXT_STEPS.md`.
- `forcegeo/galileo-design/*.dc.html` need the design-canvas runtime, which is not part of the repo (see known issues).
- Generated pages are long by design: `greenops/ui/dashboard.html`, `greenops/globe/earth.html` and
  `forcegeo/galileo-live/galileo-live.html` embed data and are rebuilt by their `build.py`; edit the
  `template.html` next to them instead.

## Context docs

`docs/context/` describes how the repo works. Read the relevant file before touching code, and update it in the
same commit as the change it describes.

| Document | Update when |
| --- | --- |
| `docs/context/architecture.md` | The stack, directory structure or entry points change |
| `docs/context/conventions.md` | Code, test or commit conventions change |
| `docs/context/decisions.md` | An architecture decision is made (one ADR entry per decision) |
| `docs/context/glossary.md` | A domain term appears or changes meaning |
| `docs/context/workflow.md` | Commands, verification order or the release/submission process change |
| `docs/context/known-issues.md` | You hit a recurring error or an environment trap |

## Language

- Reply in the language the person writes in; don't guess it from the name.
- Everything committed is English: code, comments, identifiers, file names, docs, commit messages, PR text.

## Working style

- Work on a branch, open a pull request, merge when the **tests** check is green.
- Run `python -m pytest -q` from `greenops/` before pushing changes under `greenops/`.
- Add or update tests for scheduling logic, the residency guard and the export data contract.
- Prefer small, focused diffs over rewriting whole files; review your own change before finishing.
- Keep hand-written files well under 1000 lines; add a sub-package for a new product area instead of growing one file.
- Use your tool's own scratch directory for temporary files; never commit scratch files.

## Optional skills

Community skill packs (for example from www.skills.sh) are welcome when your tool can load them, but they are
never required and nothing in the repo may depend on them. What we do expect is stated in plain words above:
tests for logic changes, small diffs, review your own change. If a pack is unavailable, don't stall — carry on
with the rules in this file.
