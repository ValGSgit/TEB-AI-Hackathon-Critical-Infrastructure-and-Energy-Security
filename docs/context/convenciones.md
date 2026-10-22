# Conventions

- Language: all code, comments, variable names, file names and generated documentation are in English.
  The user communicates in Spanish, but repo content stays English.
- Python version: 3.11+ (README), 3.12 in CI and Dockerfile.
- Dependency file: `greenops/requirements.txt` (exoscale, requests, pytest). Install with `pip install -r requirements.txt`.
- Tests: pytest, configured in `greenops/pytest.ini` (`pythonpath = .`, `testpaths = tests`).
  Run from `greenops/`: `python -m pytest -q`.
- Naming: snake_case modules/functions, PascalCase dataclasses, policy classes `Baseline` / `CarbonAware`.
- Keep planner logic free of scenario-specific knowledge; the local simulator randomizes durations/times per seed.
- Credentials: read from environment (`EXOSCALE_API_KEY`, `EXOSCALE_API_SECRET`). Never commit credentials.
- Git: work on a branch, open a pull request, merge only when the tests check is green.
- Challenge rule: only forecasts published for the current run may be used; never store actual future values in code or config.
- Residency rule: every placement goes through `greenops/guard.py`; keep it that way (checked twice before every create).
- UI data contract: JSON schemas are versioned (`schema: 1`); bump the schema and update `tests/test_export.py` when it changes.
- Keep files under ~1000 lines where practical; new sub-packages for a new product area instead of growing one file.
