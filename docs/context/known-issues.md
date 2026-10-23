# Known Errors / Gotchas

- **Scores are approximations offline.** `sim.py` (synthetic path) uses a stand-in formula and `game.py` approximates
  greenops-score-v2 from its published constants. Only the platform's dashboard score is real.
- **Synthetic path still uses assumed numbers.** `catalog.py` / `scenario.py` keep their ASSUMED values for the Control
  Room samples; the real numbers live in `greenops/challenge/` via `spec.py`.
- **Forecast horizon is 24 h.** 48 and 72 are rejected by the API. Beyond 24 h the planner guesses (blend + premium).
- **Postponing.** Hourly re-planning can push flexible starts later until slack runs out (seen in both practice runs:
  `w-05-eu-render` briefly blocked, finished 1.7–1.9 h before its deadline). First item in `greenops/NEXT_STEPS.md`.
- **Timestamps.** The work status sends fractional seconds of any length (`…40.91+00:00`); Python < 3.11 rejects them
  in `fromisoformat`. `spec.to_h` normalizes them.
- **Windows.** Set `PYTHONUTF8=1` (the `exoscale` package reads its spec with the default encoding), and check the
  config isn't saved as `greenops-exo.json.json`. In Git Bash use `MSYS_NO_PATHCONV=1` for Docker volume paths.
- **Proxy in tests.** The fake platform listens on 127.0.0.1; tests set `NO_PROXY` so requests don't go through a proxy.
- **Exoscale executor.** `greenops/greenops/exoscale_exec.py` is the pre-event scaffold, superseded by `live.py`.
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
