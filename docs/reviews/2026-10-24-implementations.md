# Review: A (`run2-code`) vs B (`main`) — security, correctness, risk

Date: 2026-10-24
Reviewer: AI assistant
Branches inspected: `origin/submission/run2-code` (A), `origin/main` (B)

## Summary

| Area | A (`run2-code`) | B (`main`) |
|------|-----------------|------------|
| Commit | `1e1a770` | `d01ec2a` |
| Tests (pytest -q) | **38** (no `test_forecast.py`, no `test_analyze.py`, no `test_residency.py`, no `test_decision_log_contract.py`) | **92** |
| `planner.py` lines | 322 | 407 |
| `live.py` lines | 405 | 521 |
| Practice runs documented | Run 1–2 only | Runs 1–6 |
| Key safety features | Basic | All post-run-2 fixes present |

---

## F1 — A: No rescue pass → starvation of flexible jobs [HIGH]

**Severity:** HIGH — disqualifies the run if it happens under the judges.
**Affects:** A.
**Files:** `greenops/greenops/planner.py`

### What
A lacks the entire rescue/urgent path (ADR-0013). `_replan()` has a single pass: plan all jobs, mark no-one urgent, no second pass, no flat-out fallback.

### Risk
When quota is tight late in the run, jobs that were planned as "flexible" (e.g. `w-05-eu-render` with `max_workers=10`) are scheduled last and can be pushed past their deadline. This is exactly what happened in practice run 3: `w-05` was left without a slot from hour 79 to the end, missing the 5,000-point completion bonus.

### Evidence
Run 3 log (`.local/run3/decisions.jsonl:72–94`) — `w-05` blocked from hour 79, no `create` logged after. Offline repro: `Planner(spec, f, rescue=False, urgent_late=False)` on 240 vCPUs delivers <15/15 on some seeds.

### Fix
Apply ADR-0013 to A: add `rescue`, `urgent`, `urgent_late`, `_late` fields, the two-pass `_plan_pass`, and the "flat out" fallback in `_replan()`.

---

## F2 — A: No `slack_h` soft-end rule → systematic postponing [MEDIUM]

**Severity:** MEDIUM — tightens slack to ~2 h, leaving almost no margin.
**Affects:** A.
**Files:** `greenops/greenops/planner.py`

### What
A does not plan jobs to finish before their soft end. There is no `slack_h`, no `soft` variable, no `_late` set. The planner optimises purely over `[first, last]` with no buffer.

### Risk
Both practice runs 1 and 2 showed `w-05-eu-render` finishing 1.9–2.0 h before its deadline, right at the edge. Any small platform delay would push it late. The ADR notes that after adding `slack_h=4`, the tightest job improved to 6.3 h slack on 32 seeds.

### Fix
Apply ADR-0012: add `slack_h=4`, `soft = last - self.slack_h`, plan `[soft, last]` before `[last]`, and fall back to full window when the soft end is unreachable.

---

## F3 — A: No `commit_h` → starts can drift at every re-plan [LOW]

**Severity:** LOW — causes late starts but the job still finishes on time in practice.
**Affects:** A.
**Files:** `greenops/greenops/planner.py`

### What
A lacks `commit_h` and `commit` on `Slot`. A start planned within `commit_h=2` hours is never "kept" — it is re-optimised away at every hourly re-plan, causing the same drift seen in runs 1/2 (e.g. `w-15`: 37→74).

### Risk
In combination with F2, drift pushes flexible starts later. On its own it does not cause a miss because `margin_h=2` absorbs it. But with `slack_h` (F2 fix) it is needed to stabilise starts close to the current hour.

### Fix
Apply ADR-0012: add `commit_h=2`, `commit` field on `Slot`, and the keep-start logic in `_plan_pass()`.

---

## F4 — A: No `finish_h` late-run flat-out mode [HIGH]

**Severity:** HIGH — a single long stall near the end can strand a nearly-done job.
**Affects:** A.
**Files:** `greenops/greenops/planner.py`

### What
A lacks `finish_h`. A created job with ≤12 run hours left never runs flat-out. When the platform stalls (a 65 s reply = ~13 simulated hours at 720×), a paused nearly-finished job can be resumed after its deadline.

### Risk
Practice run 5: `w-03-med-analysis` missed its deadline (87.9%) because it had been stopped with ~6 run hours left and the platform was slow to reply. With `finish_h=12` the same scenario delivers 15/15. Offline: 1/12 grids fully on time without the rule → 12/12 with it.

### Fix
Apply ADR-0015: add `finish_h=12.0`, and in `_best_block` pass `stretch=(1.0,)` when `need <= self.finish_h`.

---

## F5 — B: `safe_actions` runs unfinished work blindly [MEDIUM]

**Severity:** MEDIUM — carbon cost if planning fails, but better than staying stopped.
**Affects:** B.
**Files:** `greenops/greenops/live.py:324–335`

### What
When `planner.decide()` raises, `safe_actions` starts every stopped VM of every unfinished workload. It does not check residency or quota.

### Risk
If a forecasting failure triggers `safe_actions` late in the run with no forecast available, VMs could be started in zones the job is not allowed in. This would cause a residency violation and disqualify the run. The probability is very low (all 8 areas must fail forecast simultaneously), but the consequence is fatal.

### Suggested fix
Add a residency guard inside `safe_actions`: skip starting a VM in a zone not in `w.allowed_countries`. Alternatively, make `safe_actions` only start VMs whose planned zone is legal. Mark with `pytest.mark.xfail` and the finding number until fixed.

---

## F6 — A: No stale-forecast fallback [MEDIUM]

**Severity:** MEDIUM — planning stops if the grid API fails for any area.
**Affects:** A.
**Files:** `greenops/greenops/live.py`

### What
A's `Live.forecast` makes one synchronous HTTP call per area with `timeout=20`. If the request hangs or returns an error, the exception propagates to the caller (`_estimates`), which propagates to `_replan`, which propagates to `main`. There is no `_stale`, no `fc_last`, no `fc_failed`.

### Risk
Practice run 6 (B): forecast requests timed out and planning stopped, leaving a paused job stopped past its deadline. The fix in B adds `_stale()` which uses the last known forecast for that area. A has no equivalent.

### Suggested fix
Apply A's `Live._stale` + `prefetch` + `fc_last`/`fc_failed` logic from B. Until then, a single forecast timeout stalls the controller.

---

## F7 — A: 10 s status timeout loses polls on a slow platform [MEDIUM]

**Severity:** MEDIUM — each lost poll means up to ~2 simulated hours of inaction.
**Affects:** A.
**Files:** `greenops/greenops/live.py:164`

### What
A uses `timeout=10` (single value, no tuple). B uses `timeout=(5, STATUS_TIMEOUT_S)` with `STATUS_TIMEOUT_S = 60`.

### Risk
Practice run 4: the platform took 10–20 s to reply to `/work/v1/status`. With a 10 s timeout, A lost 26 polls in that run. Each lost poll wastes up to 0.5 simulated hours of scheduling decisions. In B, `STATUS_TIMEOUT_S=60` eliminated this.

### Suggested fix
Set `STATUS_TIMEOUT_S = 60` in A, change `timeout=10` → `timeout=(5, STATUS_TIMEOUT_S)`.

---

## F8 — A: No slow-poll logging [LOW]

**Severity:** LOW — diagnostic blind spot, not a correctness bug.
**Affects:** A.
**Files:** `greenops/greenops/live.py`

### What
A has no timing instrumentation in the control loop. There is no `slow_poll_s` warning when a poll exceeds 2 wall seconds.

### Risk
Cannot diagnose why a run has low sample counts or idle VMs. Hard to distinguish a slow platform from a controller hang.

### Suggested fix
Add the `t0/t1/t2/t3` timing blocks and the `slow_poll_s` print from B's `main()`.

---

## F9 — A: No parallel forecast prefetch [LOW]

**Severity:** LOW — adds latency but not correctness risk.
**Affects:** A.
**Files:** `greenops/greenops/live.py`

### What
A fetches forecasts sequentially: 8 areas × 1 round-trip each = up to 8 × 20 s = 160 s in the worst case per re-plan. B uses `ThreadPoolExecutor` to fetch all 8 in parallel (~20 s worst case).

### Risk
At 720×, 1 s wall = 0.2 sim hours. 160 s = 32 simulated hours of potential delay. In practice the grid API is fast (most replies <1 s), so the impact is small. But a slow or busy platform amplifies this.

### Suggested fix
Port B's `prefetch()` and the `fc_cache` / `fc_last` / `fc_failed` logic.

---

## F10 — A: No parallel action execution [LOW]

**Severity:** LOW.
**Affects:** A.
**Files:** `greenops/greenops/live.py`

### What
A sends stop/start/delete actions sequentially. B uses `act_parallel()` with a thread pool (workers=8) so they go out concurrently.

### Risk
In run 6 (B), one action took 17.6 s; with sequential execution, a poll with six actions could take >100 s. Parallel execution reduces the wall time to ~17 s. At 720× that is ~3.4 sim hours vs ~20 sim hours.

### Suggested fix
Port B's `act_parallel()` and integrate it into `main()` for the non-create action path.

---

## F11 — A: Deletes not run before other actions [LOW]

**Severity:** LOW — wasted carbon from idle VMs.
**Affects:** A.
**Files:** `greenops/greenops/live.py`

### What
In A, `decide()` returns actions sorted `delete < stop < start < create`. They are then executed in that order by `for act in actions: live.act(...)`. So deletes do go first. However, A does not delete VMs proactively in the loop — it relies on `decide()` producing delete actions. B explicitly deletes before fetching forecasts and planning.

### Risk
If `planner.decide()` is delayed (e.g. due to sequential forecast fetches from F7), delivered VMs stay running longer, drawing idle power. The impact is small because the action order is still correct, but B is more defensive.

---

## F12 — A: Test coverage gap — no residency cross-product test [HIGH]

**Severity:** HIGH — the most important invariant is untested.
**Affects:** A.
**Files:** `tests/test_residency.py` (missing in A)

### What
A has no `test_check_placement_matches_spec_for_all_pairs`. B has it: every workload × every zone (15 × 11 = 165 pairs) is checked. Without it, a future refactor of `guard.py` or `spec.py` could silently break a residency constraint.

### Suggested fix
Port the test from B. Add a failing test if the pair-check is not yet in place.

---

## F13 — A: Test coverage gap — no end-to-end stall test [HIGH]

**Severity:** HIGH — the exact failure mode from run 5 is untested.
**Affects:** A.
**Files:** `tests/test_planner.py` (partial in A)

### What
A has no `test_a_long_platform_stall_does_not_strand_a_nearly_done_job`. This test simulates a 15-hour stall at hour 103 and asserts `finish_h=12` prevents a miss. Without it, a regression of the stall guard would not be caught.

### Suggested fix
Port the test from B. It should fail against A's code (which lacks `finish_h`), demonstrating the gap.

---

## F14 — A: Test coverage gap — no analyze edge cases [MEDIUM]

**Severity:** MEDIUM — a crash in `analyze.py` on a torn log would block post-run analysis.
**Affects:** A.
**Files:** `tests/test_analyze.py` (missing in A)

### What
A has no tests for torn JSONL lines, missing `console.log`, undelivered workloads, or restart semantics. These are real failure modes observed during the event (run 1 crashed on a `.91` timestamp, run 3 left a torn `status.jsonl`).

### Suggested fix
Port the 6 edge-case tests from B.

---

## F15 — A: CI runs fewer checks [LOW]

**Severity:** LOW — regression surface is smaller.
**Affects:** A.
**Files:** `.github/workflows/tests.yml`

### What
A's CI runs: `pytest -q`, `compare.py 5`, `greenops.play --seeds 2`. B's CI additionally runs `export_game --ladder 2 && ui/build.py && globe/build.py` and `site/build.py`. The UI build is not critical for judging but the `export_game` validation catches schema regressions.

### Suggested fix
Port B's CI steps to A, or accept the reduced coverage.

---

## F16 — B: `GREENOPS_PLANNER` environment variable referenced but not implemented [INFO]

**Severity:** INFO — not a bug in the current code, but the prompt mentions three profiles (`default`, `adaptive`, `run2plus`).
**Affects:** Both (expected behaviour not yet implemented).
**Files:** None currently.

### What
The task description references `GREENOPS_PLANNER=default|adaptive|run2plus` but `main` (commit `d01ec2a` / `24da484`) has no such variable. The current `main` always uses the full safety-rule planner. The `adaptive` and `run2plus` profiles described in ADR-0016–0017 do not yet exist in code.

### Risk
If the submission is expected to include these profiles, they are not present. This is not a bug in A or B — it is a missing feature. Flag it for clarification.

---

## Security (both A and B)

### Residency guard — passes ✅
Both A and B check placement twice: in `planner.decide()` (line 346 B / 264 A) and in `Live.create()` (line 268 B / 206 A). No path bypasses the guard. Adoption after restart (`planner._adopt`) builds the placement from legal zones and then checks it again in `decide()`.

### Only forecasts (rule 2) — passes ✅
Both A and B receive electricity data exclusively through the `forecast(area, now)` callable. No actuals, no stored series, no other runs. B's `_stale()` reuses only this run's own earlier forecasts (shifted in time), which is compliant.

### URL scope enforcement — passes ✅
Both use `RunOnlyAdapter` and `check_endpoint`. A's `check_endpoint` also rejects `exoscale.com` hostnames. B has the same plus a work-endpoint check (`GREENOPS_WORK_ENDPOINT` must match the cloud run).

### Secrets in logs — passes ✅
Neither A nor B print API keys, secrets, or tokens to stdout/stderr. The only values that appear in `print()` calls are warnings, plan summaries, and decision logs. `git ls-files | grep -iE "exo.*json|\.env$"` shows only `credentials.example.env` in both.

### Docker image — passes ✅
Both A and B share the same `Dockerfile`: `python:3.13-slim`, non-root user (`greenops`, uid 10001), read-only root, writes only to `/tmp`.

---

## Correctness under adverse conditions

| Condition | A (`run2-code`) | B (`main`) |
|-----------|-----------------|------------|
| Status timeout (10 s reply) | Loses the poll; retries after 2 s sleep | Waits up to 60 s; retries after 0.5 s |
| Forecast timeout | Exception propagates; planning fails next poll | Falls back to `_stale()` (last known forecast) |
| Refused create/start/delete | Logged via `planner.rejected()`; retried next poll | Same, plus parallel execution |
| 409 "run finished" on delete | Treated as any other refusal; retried next poll | Same |
| Controller restart (adopt) | Works: `_adopt` rebuilds placement from existing VMs | Same |
| Job can no longer finish | Planned with no slot; stays "blocked" forever | Same (the rescue pass only helps if it *can* finish) |
| End of run (hour 120) | `_best_block` check: `e > last + 1` break. No overflow protection for the `created` fallback path when `need` pushes `end` past H. | Same fallback, but with an explicit `min(self.H, ...)` clamp (line 281) that prevents `IndexError`. |
| Long stall (>12 h) late in run | Job pauses, may miss deadline | `finish_h=12` keeps it running flat-out |
| Spare-time-crowding starvation | **No rescue pass. Job can starve.** | Rescue pass + urgent + late flag |
| No console.log at end | `run["end"]` is None; controller exits normally on `horizon_h` check | Same |

---

## Recommended submission

**Submit B (`main`)**. It incorporates all fixes learned from runs 3–6:
- Rescue pass prevents starvation (F1)
- `slack_h=4` gives reliable slack (F2)
- `commit_h=2` stabilises starts (F3)
- `finish_h=12` guards against late stalls (F4)
- Stale forecast fallback prevents planning freezes (F6)
- 60 s status timeout matches platform behaviour (F7)
- Parallel prefetch + parallel actions match the 720× timing budget (F9, F10)
- Full test suite (92 tests) covers all regression paths (F12–F14)

**A (`run2-code`) is not submission-ready** because:
- It lacks the starvation rescue (F1) — a single tight-quota scenario can lose the completion bonus.
- It lacks the stall guard (F4) — a single slow platform reply near the end can lose a job.
- It has 54 fewer tests, leaving the most critical invariants (residency cross-product, stall recovery) untested.

The only case where A might be preferred is if the judges specifically want the "simplest working scheduler" as a baseline comparison. But the judging criterion is score (carbon), and B's fixes improve score reliability without material carbon penalty (ADR-0015: −0.25% on a normal platform).
