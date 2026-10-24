# Submission: GreenOps orchestrator (team CryptoNight)

## Form fields

| Field | Value |
| --- | --- |
| GitHub repository URL | https://github.com/ValGSgit/TEB-AI-Hackathon-Critical-Infrastructure-and-Energy-Security |
| Full commit SHA | the `main` commit the team submits (in `greenops/.local/SESSION_HANDOFF.md`; it can't be written inside the commit itself) |
| Claimed practice run | the finalized run of that code (see `greenops/NEXT_STEPS.md`, "Start here") |
| Reproducible build and run instructions | the block below |

## Reproducible build and run instructions

```text
Requirements: Docker. Everything the controller needs is in the image; no other files are read.

1. Build (from the repository root, at the submitted commit):
   docker build -t greenops greenops

2. Run against a fresh run that is READY (our first VM create starts the run clock):
   docker run --rm --read-only --tmpfs /tmp --cpus 2 --memory 1g \
     -e EXOSCALE_API_KEY -e EXOSCALE_API_SECRET -e GREENOPS_CLOUD_ENDPOINT \
     -e GREENOPS_GRID_SECRET \
     greenops

   Required environment: EXOSCALE_API_KEY, EXOSCALE_API_SECRET, GREENOPS_CLOUD_ENDPOINT
   (https://<host>/runs/<run-id>/cloud/v2) and GREENOPS_GRID_SECRET.
   Optional: GREENOPS_GRID_ENDPOINT and GREENOPS_WORK_ENDPOINT (derived from the cloud endpoint; if given,
   they must belong to the same run). GREENOPS_PLANNER (default: adaptive, the judged configuration).
   Alternatively mount the run's downloaded CLI config and pass it:
     -v "$PWD/greenops-exo.json:/cfg/greenops-exo.json:ro" ... greenops --config /cfg/greenops-exo.json
   with GREENOPS_GRID_SECRET in the environment.

3. The controller runs by itself until every workload is delivered and its VMs are deleted, or the run ends.
   It writes its decision log and status samples to /tmp/greenops-run inside the container. To keep them:
     -v "$PWD/out:/tmp/out" ... greenops --out /tmp/out

Read-only check first (creates nothing): add --probe to the run command.
Image: python:3.13-slim, non-root (uid 10001), read-only root filesystem, writes only to /tmp,
pinned dependencies (greenops/requirements.txt). Tests: cd greenops && pip install -r requirements-dev.txt
&& python -m pytest -q.
```

## What is judged

- Planner profile `adaptive` (the default): it plans like our best practice run while the platform answers
  quickly, and switches the stall rules on by itself once a gap between status replies exceeds 0.75 simulated
  hours. See `docs/context/decisions.md`, ADR-0012 to ADR-0018.
- The residency guard is checked twice for every create. The only electricity input is this run's own
  published forecast. Every request stays inside the run's URL prefix, and credentials come only from the
  environment.
