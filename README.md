# TEB AI Hackathon: Critical Infrastructure & Energy Security

Friday 23 October 2026, 16:00 – Sunday 25 October 2026, 19:00 · weXelerate, Vienna

Team repo. Everything we build, before and during the event, goes here.

## What is in the repo

| Folder | What it is | Status |
| --- | --- | --- |
| [`greenops/`](greenops/) | Carbon-aware scheduler for the **Exoscale GreenOps Challenge** (our primary challenge) | Real-challenge planner, live API client and Docker image (see greenops/README.md) |
| [`greenops/ui/`](greenops/ui/) | GreenOps Control Room: decision explainer, block/run-hours visualization, forecast panel, decision feed | Built from simulator runs; feeds from real-run decisions.jsonl |
| [`greenops/globe/`](greenops/globe/) | GreenOps Earth: 3D replay of a run on the real map with the 11 challenge zones by carbon intensity | Built from simulator runs |
| [`forcegeo/showcase/`](forcegeo/showcase/) | ForceGeo: location-trust checks for pipeline commands, on the real TAG/SOL gas corridor | Interactive demo page (backup for an open security track) |
| [`forcegeo/galileo-live/`](forcegeo/galileo-live/) | Live Galileo and Sentinel-2 positions from real orbit data | Demo page, built from `template.html` |
| [`forcegeo/galileo-design/`](forcegeo/galileo-design/) | Two screens: authentic Galileo sky vs a replay spoofing attack at the Murfeld sensor | Design files and the script that computes the real sky |
| [`docs/`](docs/) | Challenge analysis and the Friday checklist | |

## Quick start

GreenOps orchestrator (Python 3.12+):

```bash
cd greenops
pip install -r requirements-dev.txt
pytest                      # 34 tests, incl. the residency rule that can disqualify a run
python -m greenops.play --seeds 4           # planner vs baselines on the offline game
python compare.py 20        # baseline vs carbon-aware on 20 practice scenarios
python -m greenops.experiments --seeds 12   # experiment ladder (feeds the Control Room)
python -m greenops.live                       # against real Exoscale API (set env vars)
```

GreenOps Control Room:

```bash
cd greenops
python -m greenops.export --seed 3 && python ui/build.py   # then open ui/dashboard.html
python globe/build.py                                      # then open globe/earth.html (3D view)
```

ForceGeo pages: open `forcegeo/showcase/index.html` or `forcegeo/galileo-live/galileo-live.html` in a browser.
To rebuild Galileo Live after refreshing the orbit data:

```bash
python forcegeo/galileo-live/build.py
```

## Working rules

- Work on a branch, open a pull request, merge when the **tests** check is green.
- Never commit credentials. The Exoscale executor reads `EXOSCALE_API_KEY` and `EXOSCALE_API_SECRET` from the environment.
- GreenOps rule: placing a workload in a forbidden country disqualifies the run. Every placement goes through `greenops/guard.py`; keep it that way.
- GreenOps rule: use only the forecasts published for the current run. No scenario-specific future values in code or config.

## Open questions for the organizers

1. Is code written before the event allowed?
2. Can a team enter more than one challenge, and do the security tracks have a jury and prize?
3. When do GreenOps portal access and the starter kit open?