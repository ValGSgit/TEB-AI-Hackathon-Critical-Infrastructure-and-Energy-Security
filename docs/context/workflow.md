# Workflow

## Commands

GreenOps scheduler (from `greenops/`):

```bash
pip install -r requirements.txt
python -m pytest -q        # about 99 tests, about 2–5 min
python -m greenops.play --seeds 8                           # real-challenge planner on the offline game
python compare.py 20                                        # earlier synthetic path
python -m greenops.experiments --seeds 12
python -m greenops.export_game --seed 3 --ladder 8 && python ui/build.py   # -> ui/dashboard.html (real path)
python globe/build.py                                      # -> globe/earth.html
```

ForceGeo pages: open `forcegeo/showcase/index.html` or `forcegeo/galileo-live/galileo-live.html` in a browser.
`forcegeo/galileo-design/*.dc.html` cannot be opened directly: they need `./support.js` from the design-canvas
runtime, which is not in the repo. View them in the published design canvas; the files here are the source. Rebuild
Galileo Live after refreshing orbit data:

```bash
python forcegeo/galileo-live/build.py
python forcegeo/galileo-design/compute_sky.py   # -> sky2.json (needs skyfield + numpy)
```

## Practice and judged runs

See `greenops/NEXT_STEPS.md` ("How to run") for the full steps. In short, from `greenops/`, with the run left READY
(our first create starts the clock):

```bash
python -m greenops.live --probe --out .local/probe      # read-only: zones, types, forecast shape, plan
python -m greenops.live --out .local/runN               # the run; restart it if it dies (it adopts VMs)
docker build -t greenops greenops                       # judged image (Python 3.13)
```

Credentials: `greenops-exo.json` in the repo root, plus the grid secret in `.env` or `greenops/.local/greenops.env`
(template: `greenops/credentials.example.env`). All git-ignored. Real-run carbon values stay out of git.

## Project site (GitHub Pages)

`python site/build.py` writes `site/dist/` (git-ignored); open `site/dist/index.html`. On every push to `main`,
`.github/workflows/pages.yml` builds it into `_site` and deploys it. One-time setup in the repo settings:
Pages → Source: GitHub Actions. Edit `site/template.html`, never the built page. Only synthetic data goes in.

## CI (`.github/workflows/tests.yml`)

- `greenops`: `pip install -r requirements-dev.txt`, `pytest -q`, `compare.py 5`, `greenops.play --seeds 2`.
- `galileo-live`: `python forcegeo/galileo-live/build.py`.
- `greenops-ui`: legacy experiments + export (smoke test), `export_game` + `ui/build.py` + `globe/build.py`.

## Working rules

- Work on a branch, open a pull request, merge when the tests check is green.
- Never commit credentials. `greenops.live` reads the run config or `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET` /
  `GREENOPS_CLOUD_ENDPOINT` / `GREENOPS_GRID_SECRET` from the environment or a git-ignored env file.
- GreenOps rule: a workload placed in a forbidden country disqualifies the run; every placement goes through
  `greenops/greenops/guard.py`.
- GreenOps rule: use only forecasts published for the current run.

## Environment

- Python 3.12 (CI), 3.13 (Docker image, what the judges run); 3.10+ works locally.
- Docker: `greenops/Dockerfile` (`python:3.13-slim`, unprivileged, `ENTRYPOINT ["python", "-m", "greenops.live"]`).
