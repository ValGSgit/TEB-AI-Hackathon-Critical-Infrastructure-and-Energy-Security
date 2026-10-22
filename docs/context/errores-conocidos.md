# Known Errors / Gotchas

- **Scoring is a stand-in.** `greenops/sim.py` implements a local formula (20,000 base + 5,000 all-done bonus).
  The organizers' frozen scoring policy must replace it on Friday.
- **Assumed numbers pending Friday.** `greenops/catalog.py` marks zone IDs, GPU memory, zone->GPU mapping, durations,
  deadlines and power values as ASSUMED; they are replaced from the starter kit via `greenops/loaders.py`.
- **Forecast tail.** The planner uses a 48 h forecast; beyond it, the last-day mean is assumed.
- **Exoscale executor TODOs.** `greenops/exoscale_exec.py` still has placeholders for user-data format, work-status API
  shape, instance-type naming, template ID and run clock. Credentials come from `EXOSCALE_API_KEY` / `EXOSCALE_API_SECRET`.
- **Galileo design pages.** `forcegeo/galileo-design/*.dc.html` reference `./support.js`, which is not part of the repo.
- **Sky computation.** `forcegeo/galileo-design/compute_sky.py` needs `skyfield` and `numpy` and writes `sky2.json`
  (git-ignored).
- **Idle VMs.** Finished VMs keep drawing power until deleted; ablation knob `keep_idle` in the policy.
- **Rejected placements.** The real platform may reject a residency attempt, but the run is still disqualified; the
  simulator raises `ResidencyViolation`.
