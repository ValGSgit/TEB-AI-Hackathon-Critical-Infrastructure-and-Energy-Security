# AGENTS.md

Instructions for any coding assistant working in this repo (Claude, Codex, Cursor, opencode, ...).
Team of three; each of us uses a different tool, so everything here must work without tool-specific features.

## Hard rules (read first)

1. **Residency.** Never place a GreenOps workload in a country outside its allowed list. Every placement goes
   through `greenops/greenops/guard.py`; do not bypass or weaken it. A single forbidden attempt disqualifies the
   whole run, even if the API rejects it.
2. **Forecasts only.** The scheduler may use only the electricity forecasts published for the current run. Never
   commit actual or future carbon values for a scenario, or a schedule built from them.
3. **No credentials in git.** Exoscale keys come from `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET` in the environment.
4. **Don't overwrite existing work.** Read the code and `docs/context/` before changing structure; extend, don't replace.

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

- Reply in the language the person writes in (Valentino: English, Oliver: Spanish).
- Everything committed is English: code, comments, identifiers, file names, docs, commit messages, PR text.

## Working style

- Work on a branch, open a pull request, merge when the **tests** check is green.
- Run `python -m pytest -q` from `greenops/` before pushing changes under `greenops/`.
- Add or update tests for scheduling logic, the residency guard and the export data contract.
- Prefer small, focused diffs over rewriting whole files; review your own change before finishing.
- Keep hand-written source files small (aim for well under 1000 lines). Generated pages are exempt:
  `greenops/ui/dashboard.html`, `greenops/globe/earth.html` and `forcegeo/galileo-live/galileo-live.html` embed
  data and are rebuilt by their `build.py`; edit the `template.html` next to them instead.
- Use your tool's own scratch directory for temporary files; never commit scratch files.

## Optional skills

If your tool supports them, these community skills fit how we work. They are suggestions, not requirements, and
nothing in the repo may depend on them: TDD for scheduling logic, systematic debugging, self code review,
minimal diffs.
