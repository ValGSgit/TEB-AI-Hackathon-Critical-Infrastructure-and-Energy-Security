# Known Errors / Gotchas

- **Scoring is a stand-in.** `greenops/greenops/sim.py` implements a local formula (20,000 base + 5,000 all-done bonus).
  The organizers' frozen scoring policy must replace it on Friday.
- **Assumed numbers pending Friday.** `greenops/greenops/catalog.py` marks zone IDs, GPU memory, zone->GPU mapping, durations,
  deadlines and power values as ASSUMED; they are replaced from the starter kit via `greenops/greenops/loaders.py` (to be written).
- **Forecast tail.** The planner uses a 48 h forecast; beyond it, the last-day mean is assumed.
- **Exoscale executor TODOs.** `greenops/greenops/exoscale_exec.py` still has placeholders for user-data format, work-status API
  shape, instance-type naming, template ID and run clock. Credentials come from `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET`.
- **Galileo design pages.** `forcegeo/galileo-design/*.dc.html` reference `./support.js` from the design-canvas runtime,
  which is not part of the repo, so they do not open directly in a browser. View them in the published design canvas.
- **Sky computation.** `forcegeo/galileo-design/compute_sky.py` needs `skyfield` and `numpy` and writes `sky2.json`
  (git-ignored).
- **Idle VMs.** Finished VMs keep drawing power until deleted; ablation knob `keep_idle` in the policy.
- **Rejected placements.** The real platform may reject a residency attempt, but the run is still disqualified; the
  simulator raises `ResidencyViolation`.
- **Generated pages.** Editing `greenops/ui/dashboard.html`, `greenops/globe/earth.html` or
  `forcegeo/galileo-live/galileo-live.html` by hand is lost on the next build; edit the `template.html` instead.
- **Shallow clones.** A `git clone --depth 1` only tracks `main`; add
  `git config --add remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` to see other branches.
- **Embedded git repos.** Never copy a folder that contains its own `.git` into the repo: git stores a pointer
  instead of the files (this happened once with the first `greenops/` upload).
