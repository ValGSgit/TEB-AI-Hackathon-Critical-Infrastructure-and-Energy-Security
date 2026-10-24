# Decisions (ADRs)

- **ADR-0001**: Primary challenge chosen: Exoscale Carbon-Aware Cloud Orchestration (`greenops/`). Best fit for our
  team of three (pure engineering, measurable outcome, pre-buildable). Backup: ForceGeo (`forcegeo/`) for the open
  security track.
- **ADR-0002**: Pre-build before the event using a local simulator and clearly marked stand-ins (scoring, durations,
  forecasts). Friday checklist: write `greenops/greenops/loaders.py`, fill executor TODOs, replace stand-in score, practice run.
- **ADR-0003**: Scheduling architecture: `Baseline` (fixed legal zone, start at release) vs `CarbonAware` (forecast-driven,
  replan every tick; options at release, wait for cleaner hours with safety margin, quota to tightest slack first, delete
  idle VMs). Experiment ladder runs one change at a time on shared seeds.
- **ADR-0004**: Residency guard is mandatory and checked twice (policy + executor) because a forbidden-country placement
  disqualifies the whole run even if the API rejects it.
- **ADR-0005**: UI and 3D globe consume a versioned JSON run export produced by `greenops.export` from the local
  simulator; a second exporter from the real platform is expected on Friday with no UI changes.
- **ADR-0007**: Vendor the organizers' public spec (`greenops/challenge/*.json`, hash-checked against their manifest)
  and load it with `spec.py` into the existing model, instead of hand-copying numbers. Public data only: no electricity
  series.
- **ADR-0008**: Real-challenge scheduler is a rolling-horizon slot planner (`planner.py`), not the per-job wait rule of
  ADR-0003. Reason: stopped VMs keep quota, so per-job pausing starved late jobs of quota. Each job gets a block whose
  quota is reserved whole; it runs in the cleanest hours inside it. Beyond the 24 h forecast: same-hour/mean blend
  plus a 10% risk premium.
- **ADR-0009**: Test the live client against `tests/fake_platform.py` (the API subset served over the offline game),
  so the control loop, URLs and request shapes are covered without credentials.
- **ADR-0010**: The judged artifact is `greenops/Dockerfile` running `python -m greenops.live`, matching the judges'
  limits (2 CPUs, 1 GiB, read-only root, `/tmp` only). The controller never exits mid-run on a non-residency error and
  adopts existing VMs after a restart.
- **ADR-0011**: Project site on GitHub Pages, built in CI from `site/template.html` and the offline game
  (`site/build.py`), not committed as HTML. Its replay and benchmark use synthetic grids only, so no real-run
  electricity or carbon values are published (rule 2). The Control Room and Earth view are copied in.
- **ADR-0012**: Stop postponing in the planner. Each job is planned to end `slack_h` = 4 h before its latest end when
  that fits; a created job that no longer fits that runs every hour. A start planned within `commit_h` = 2 h is kept
  (placement and hour) and gets quota right after created jobs. Reason: both practice runs delivered `w-05` about
  2 h before its deadline. Offline (32 seeds): tightest job 2.5 → 6.3 h early, score −7 points. A fraction of the
  window and larger buffers were tried and rejected (uneven or "blocked").
- **ADR-0006**: Agent instructions live in `AGENTS.md` (imported by `CLAUDE.md`) plus `docs/context/`. They are in
  English (file names and content), tool-neutral, put the disqualifying rules first, and are updated in the same
  commit as the change they describe. External skills are optional: nothing in the repo depends on them.
