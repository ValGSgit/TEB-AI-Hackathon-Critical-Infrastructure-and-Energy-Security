# Workflow

## Commands

GreenOps scheduler (from `greenops/`):

```bash
pip install -r requirements.txt
python -m pytest -q
python compare.py 20
python -m greenops.experiments --seeds 12
python -m greenops.export --seed 3 && python ui/build.py   # -> ui/dashboard.html
python globe/build.py                                      # -> globe/earth.html
```

ForceGeo pages: open `forcegeo/showcase/index.html`, `forcegeo/galileo-live/galileo-live.html` or
`forcegeo/galileo-design/*.dc.html` in a browser. Rebuild Galileo Live after refreshing orbit data:

```bash
python forcegeo/galileo-live/build.py
python forcegeo/galileo-design/compute_sky.py   # -> sky2.json (needs skyfield + numpy)
```

## CI (`.github/workflows/tests.yml`)

- `greenops`: `pip install`, `pytest -q`, `compare.py 5`.
- `galileo-live`: `python forcegeo/galileo-live/build.py`.
- `greenops-ui`: experiments + export + `ui/build.py` + `globe/build.py`.

## Working rules

- Work on a branch, open a pull request, merge when the tests check is green.
- Never commit credentials. Exoscale executor reads `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET` from the environment.
- GreenOps rule: a workload placed in a forbidden country disqualifies the run; every placement goes through
  `greenops/guard.py`.
- GreenOps rule: use only forecasts published for the current run.

## Environment

- Python 3.12 (CI/Docker), 3.11+ (README).
- Docker: `greenops/Dockerfile` (`python:3.12-slim`, `CMD ["python", "compare.py", "10"]`).
