# Known Errors / Gotchas

- **Scores are approximations offline.** `sim.py` (synthetic path) uses a stand-in formula and `game.py` approximates
  greenops-score-v2 from its published constants. Only the platform's dashboard score is real.
- **Synthetic path still uses assumed numbers.** `catalog.py` / `scenario.py` keep their ASSUMED values for the Control
  Room samples; the real numbers live in `greenops/challenge/` via `spec.py`.
- **Forecast horizon is 24 h.** 48 and 72 are rejected by the API. Beyond 24 h the planner guesses (blend + premium).
- **Postponing.** Hourly re-planning pushed flexible starts later until slack ran out (both practice runs:
  `w-05-eu-render` briefly blocked, finished 2.0 and 1.9 h before its deadline, per `python -m greenops.analyze`).
  Mitigated by ADR-0012 (`slack_h`, `commit_h`). Run 3 then starved `w-05` completely (quota crowding); fixed
  by ADR-0013 (rescue pass).
- **Slow polls at 720×.** One wall second is 0.2 simulated hours. Run 3's loop went up to ~23 s without a poll, so
  deletes came hours late. Mitigated by ADR-0014; `live.py` prints `slow_poll_s` (status / plan / act split) for any
  poll over 2 s. Run 4 showed the platform's work-status reply itself taking 10–20 s at times, so the status
  read timeout is 60 s (`STATUS_TIMEOUT_S`, after run 6's 36 s replies) and a failed poll is retried after 0.5 s. In run 5 one reply took 65 s:
  whatever is stopped then stays stopped, so nearly finished jobs no longer pause (ADR-0015). In run 6 status took
  20 s at the median and forecast requests timed out; see ADR-0016 (stale-forecast fallback, safe mode).
- **Quiet blocked jobs.** The decision log records only state changes, so a job that stays "blocked" logs once.
  Read the absence of later lines as "still blocked".
- **Status sampling.** `status.jsonl` is sampled once per simulated hour, so a job delivered after the last sample
  has no `succeeded_at` there; `analyze.py` dates it by our delete decision (an upper bound).
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
  instead of the files (this happened with the first `greenops/` upload and again with a Feint clone in
  `feint/`, which is now git-ignored).
