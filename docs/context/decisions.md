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
- **ADR-0006**: Engineering docs live in `docs/context/` (architecture, decisions, glossary, workflow, known issues),
  in English, and are updated in the same commit as the change they describe.
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
  2 h before its deadline. Offline (32 seeds): tightest job 2.5 → 6.3 h early, score −7 points. Live (run 3) it did not stop
  w-05 from starving; see ADR-0013. A fraction of the
  window and larger buffers were tried and rejected (uneven or "blocked").
- **ADR-0013**: No job may starve. A job the planner leaves without a slot is marked urgent and planned right after
  created jobs until it is created; if it still has no slot, created jobs are planned flat out (no pauses), which hands
  back the quota their pauses would hold late in the run. A job whose only slot ends past its soft end is marked
  urgent too (the first sign of crowding). Spare time is judged on `max_workers` again: judging it on 1 worker (run 4)
  planned every parallel job first and early, squeezed the others onto slower machines without pauses, and gave a
  lower dashboard score than run 2 despite 15/15.
  Reason: run 3 left `w-05` (up to 10 workers, so it looked flexible) without a slot from hour 79 and lost the
  completion bonus. Offline with 240 vCPUs: 13.0 → 15.0 of 15 delivered; with the real 320, plans are unchanged.
- **ADR-0014**: The live loop spends as little wall time as possible: at 720× one wall second is 0.2 simulated hours.
  Delivered VMs are deleted first in every poll. Forecasts are fetched once per re-plan, cached per area and hour,
  and the 8 areas are fetched in parallel (thread-safe rate limiter). Reason: run 3 went up to ~23 wall seconds
  without a poll, and VMs idled for hours after delivery. After run 6 (actions up to 17.6 s each): stop / start /
  delete actions of a poll go out in parallel; status read timeout 60 s, forecast read timeout 10 s (with the
  stale-forecast fallback of ADR-0016).
- **ADR-0015**: Finish what is nearly done. A created job with at most `finish_h` = 12 run hours left runs them
  without pauses. Reason: run 5's platform answered one status request after 65 s (~13 simulated hours at 720×),
  and a paused, nearly finished job resumed after its deadline. Offline with a 15 h stall late in the run:
  1/12 → 12/12 grids fully on time, for −0.25% score on a normal platform. Rejected: widening every deadline
  margin by the observed poll gap (it crowded quota and did worse in stalls). Extended: a created job with at most
  `flat_slack_h` = 12 h of spare time also stops pausing (adverse-condition sweep of 192 runs: fewer misses after
  long stalls and refused actions, about −9 points on a normal platform). Not adopted: marking a job urgent after a
  refused create (no measurable effect).
- **ADR-0016**: An unreachable platform must never leave unfinished work stopped. A failed forecast request reuses
  this run's latest forecast for the area (shifted to now; still only this run's data, rule 2). If planning fails
  anyway, safe mode starts every stopped VM of an unfinished workload. The pause threshold is
  max(`flat_slack_h`, `gap_factor` = 3 × the longest gap between status replies). Reason: in run 6 forecast timeouts
  made planning fail at hour 101, and a job paused at hour 90 stayed stopped until the run ended.
- **ADR-0017**: Named planner profiles, chosen with `GREENOPS_PLANNER` (default: `default`, the judged configuration;
  ADR-0018 makes `adaptive` the default and renames the old one `safe`).
  `run2plus` plans like practice run 2 (no soft end, no kept starts, no finish / spare-time rules) and keeps the
  protections that cost nothing on a normal run (no job may starve, the end-of-run fix, the whole live loop). Adverse
  sweep, 192 runs each: run2plus is equal to run 2's code everywhere except tighter quota, where it is far safer.
  Against `default` it gains 73 points on a fast platform and loses the bonus on 9 of 16 grids when polls come every
  3 h. Run 7 and run 8 (`default`, fast platform) scored within 8 points of each other.
  `adaptive`: run 2's planning while status replies come quickly, and default's stall protections (finish_h,
  flat_slack_h, gap_factor) switch on by themselves once a reply gap exceeds `protect_gap_h` = 0.75 simulated
  hours. Same sweep: 22,008 on a fast platform (like run2plus), 16/16 with 3 h polls and with stalls at 3 h
  polls (like or better than default). Weaker than default only for a sudden stall on a fast platform
  (13 vs 14/16) and for refused actions (never seen live).
- **ADR-0018**: `adaptive` is the default profile, i.e. what the image runs with no `GREENOPS_PLANNER` set, which is
  what the judges get. The old always-on configuration is the named profile `safe` (`default` is an alias of the
  default). Reason: the choice rests on general evidence, not on the practice scenario. Offline (8 synthetic grids)
  `adaptive` scores 22,013 against 21,945 for `safe`, 15/15 on every grid, and the ADR-0017 adverse sweep keeps it
  at 16/16 with 3 h polls and stalls. Live, practice runs 9 and 10 with `adaptive` scored within 12 and 1.35 points
  of our best run (run 2), 15/15 with every safety net on, while `safe` scored about 120 points lower in runs 7
  and 8. Known cost: once one reply gap exceeds 0.75 h the stall rules stay on for the rest of the run (`gap_h` is
  the longest gap seen), and a sudden stall on an otherwise fast platform is its weakest case (ADR-0017). The
  offline benchmark (every rung of the ladder), the site and the Control Room use the same default.
- **ADR-0019**: CI guards the judged artifact itself: the `greenops` tests run on Python 3.12 and 3.13 (the image's
  version), and an `image` job builds `greenops/Dockerfile` and starts it with the judges' limits (`--help`, no
  credentials). Third-party code is never committed: the local Feint clone (the API emulator behind the platform,
  kept for reference) is git-ignored instead of tracked as a broken gitlink without `.gitmodules`.
