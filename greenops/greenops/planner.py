"""Carbon-aware planner for the real game. The same code drives the offline Game and the live API.

Inputs each tick: the work-status view (progress, delivery, VM ids/zones/states) and the run's own
carbon forecasts. Nothing else: no actuals, no other runs, no stored series.

Every simulated hour it re-plans all unfinished workloads on an hourly grid up to the end of the run:
  * Cost of running workload j in hour t = its kW (profile x workers x PUE) x estimated g/kWh of the
    zone's grid in hour t. Inside the 24-hour forecast that is the published forecast; beyond it, a
    blend of the same hour of the forecast's last day and its mean (the forecast is all we may use).
  * A workload occupies quota from its first to its last planned hour, running or stopped, because
    stopped VMs keep their quota. So for each job the planner picks a block [start, start+L) with
    L between its run time and 2x that, runs in the cleanest hours inside the block and stops in the
    others, and reserves quota (vCPUs, GPU cards, VM count) for the whole block.
  * Each job is planned to end slack_h hours before its latest end when that fits; a created job that
    no longer fits that runs every hour instead of pausing. A start planned within commit_h hours is
    kept (same placement, same hour) instead of being re-optimized later at every re-plan.
  * Jobs are planned in order of flexibility (least spare time first); created jobs first, then kept starts.
    Placement (zone, profile, workers) is chosen at the same time, among residency-legal zones only.
  * Now: a job whose block starts in this hour and whose hour is a run hour (or whose start is kept) is created; a running job
    is started or stopped according to its plan; VMs are deleted once final_output_delivered.
Every change is written to a decision log with its reason, for the Control Room.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .guard import check_placement, is_allowed
from .model import suitable, sync_throughput, throughput
from .spec import Spec


@dataclass
class Placement:
    zone_id: str
    profile_id: str
    workers: int


@dataclass
class Slot:
    """The plan for one workload: occupy [start, end) hours, run in `run` hours."""
    placement: Placement
    start: int
    end: int
    run: frozenset
    grams: float
    commit: bool = False               # start is fixed: create at `start` even if it is a pause hour


@dataclass
class Planner:
    spec: Spec
    forecast: callable                 # (area, now_h) -> hourly g/kWh from floor(now_h), 6 or 24 values
    stretch: tuple = (1.0, 1.25, 1.5, 2.0)   # block lengths tried, as multiples of the run time
    margin_h: float = 2.0              # finish this long before the deadline
    protect_gap_h: float = 0.0         # > 0: stall protections switch on only after a reply gap longer than this
    gap_factor: float = 3.0            # ... or at most this many times the longest gap between status replies seen
    gap_h: float = 0.0                 # longest gap between two status replies so far, in simulated hours
    flat_slack_h: float = 12.0         # a created job with at most this much spare time left stops pausing
                                       # (offline sweep: fewer misses after long platform stalls, -9 points normally)
    finish_h: float = 12.0             # a created job with at most this many run hours left runs them without pauses
                                       # (run 5: a 65 s status reply left a paused, nearly done job stopped past its deadline)
    beyond_blend: float = 0.5          # beyond the forecast: blend of same-hour value and forecast mean
    beyond_premium: float = 0.1       # ... plus this risk premium, so known clean hours win over guesses
    zones_per_profile: int = 2
    pause: bool = True                 # False = blocks of exactly the run time (ablation)
    shift: bool = True                 # False = start as early as quota allows (ablation)
    commit_h: int = 2                  # a planned start this close is kept, not re-optimized away (-1 = off)
    slack_h: int = 4                   # plan to end this many hours before `margin_h`, when it fits (0 = off)
    flex_workers: int = 0              # spare time is judged on this many workers (0 = the job's max_workers;
                                       # 1 moved every parallel job early in run 4 and cost ~11% more electricity)
    commit_first: bool = True          # kept starts get quota before flexible jobs
    name: str = "carbon-aware"
    placements: dict = field(default_factory=dict)    # workload id -> Placement (once created)
    vm_profile: dict = field(default_factory=dict)    # vm id -> profile id
    vm_run_h: dict = field(default_factory=dict)      # vm id -> hours seen running after release
    plan: dict = field(default_factory=dict)          # workload id -> Slot
    decisions: list = field(default_factory=list)
    _last_h: float | None = None
    _plan_hour: int | None = None
    _state: dict = field(default_factory=dict)        # workload id -> last logged state
    rescue: bool = True                # a job left without a slot is planned first, created jobs flat out if needed
    urgent: set = field(default_factory=set)          # jobs that once found no slot: planned right after created ones
    urgent_late: bool = True           # ... and jobs whose only slot runs past their soft end
    _late: set = field(default_factory=set)           # (per pass) jobs planned past their soft end

    def __post_init__(self):
        self.W = {w.id: w for w in self.spec.workloads}
        self.Z = {z.id: z for z in self.spec.zones}
        self.P = {p.id: p for p in self.spec.profiles}
        self.H = int(self.spec.horizon_h)
        if not self.pause:
            self.stretch = (1.0,)

    # ------------------------------------------------------------ electricity estimate
    def _estimates(self, now: float) -> dict:
        """area -> np.array of estimated g/kWh for every hour 0..H-1 (past hours = inf)."""
        h0, out = int(now), {}
        for area in sorted({s.area for s in self.spec.sites.values()}):
            f = np.asarray(list(self.forecast(area, now)), dtype=float)
            est = np.full(self.H, np.inf)
            n = len(f)
            for t in range(h0, self.H):
                k = t - h0
                est[t] = f[k] if k < n else (1 + self.beyond_premium) * (
                    self.beyond_blend * f[k % n] + (1 - self.beyond_blend) * f.mean())
            out[area] = est
        return out

    # ------------------------------------------------------------ remaining work
    def _rate(self, w, profile_id: str, n: int) -> float:
        return sync_throughput(throughput(self.P[profile_id], w), n, w.sync_overhead)

    def _run_hours(self, w, row, pl: Placement, created: bool) -> float:
        left = max(0.0, w.work_units - row["completed_work"])
        if created:
            staged = min((self.vm_run_h.get(a["vm_id"], 0.0) for a in row["assignments"]), default=0.0)
            boot = self.spec.boot_h if any(a["state"] == "creating" for a in row["assignments"]) else 0.0
        else:
            staged, boot = 0.0, self.spec.boot_h
        return boot + max(0.0, w.setup_h - staged) + left / self._rate(w, pl.profile_id, pl.workers) + w.output_h

    def _candidates(self, w, est) -> list:
        """Legal placements, pruned to the best zones per profile; workers grow only if needed."""
        window = w.deadline_h - max(w.release_h, 0) - self.margin_h
        out = []
        for p in self.spec.profiles:
            if not suitable(p, w):
                continue
            zones = [z for z in self.spec.zones if is_allowed(w, z) and p.available_in(z.id)]
            zones.sort(key=lambda z: z.pue * float(np.mean(est[self.spec.sites[z.id].area][np.isfinite(est[self.spec.sites[z.id].area])])))
            for z in zones[: self.zones_per_profile]:
                fit = next((n for n in range(1, w.max_workers + 1)
                            if w.setup_h + w.work_units / self._rate(w, p.id, n) + w.output_h <= window * 0.8),
                           w.max_workers)
                # the cheapest worker count, plus faster fallbacks for when quota or time gets tight
                for n in sorted({fit, min(w.max_workers, fit + 1), min(w.max_workers, 2 * fit)}):
                    out.append(Placement(z.id, p.id, n))
        return out

    # ------------------------------------------------------------ capacity
    def _need(self, pl: Placement):
        p = self.P[pl.profile_id]
        return p.vcpus * pl.workers, pl.workers, p.gpu_family, p.gpus * pl.workers

    def _fits(self, cap, pl, a, b) -> bool:
        v, n, fam, g = self._need(pl)
        if cap["v"][a:b].min() < v or cap["n"][a:b].min() < n:
            return False
        return not fam or cap[fam][a:b].min() >= g

    def _take(self, cap, pl, a, b):
        v, n, fam, g = self._need(pl)
        cap["v"][a:b] -= v
        cap["n"][a:b] -= n
        if fam:
            cap[fam][a:b] -= g

    # ------------------------------------------------------------ planning
    def _best_block(self, w, pl, need_h, h0, first, last, est, cap, fixed_start: bool, stretch=None):
        """Cheapest block for one placement: (grams, start, end, run hours) or None."""
        z = self.Z[pl.zone_id]
        p = self.P[pl.profile_id]
        cost = est[self.spec.sites[z.id].area] * p.power_kw * pl.workers * z.pue      # g per hour run
        k = max(1, math.ceil(need_h - 1e-6))
        best = None
        starts = [first] if fixed_start else range(first, last - k + 2)
        for s in starts:
            for m in stretch or self.stretch:
                L = max(k, math.ceil(k * m))
                e = s + L
                if e > last + 1 or e > len(cost):      # never past the end of the run (the caller falls back)
                    break
                if not self._fits(cap, pl, s, e):
                    continue
                win = cost[s:e]
                idx = np.argpartition(win, k - 1)[:k] if k < L else np.arange(L)
                g = float(win[idx].sum()) * (1 + 0.002 * (L - k)) + 1e-6 * s     # tiny bias: shorter, earlier
                if best is None or g < best[0]:
                    best = (g, s, e, frozenset(int(s + i) for i in idx))
            if best and not self.shift:
                return best
        return best

    def _replan(self, rows: dict, now: float):
        """Plan every job; if one is left without a slot, mark it urgent (kept until it is created) and plan again
        with it ahead of the flexible jobs; if it still has none, also run the created jobs flat out, which hands
        back the quota their pauses would hold late in the run."""
        est = self._estimates(now)        # one forecast fetch per area per re-plan, shared by every pass
        plan = self._plan_pass(rows, now, est, flat=False)
        if self.rescue:
            starved = {wid for wid, r in rows.items() if self._open(wid, r) and wid not in plan}
            if self.urgent_late:           # a slot only past the soft end is the first sign of crowding (w-05, runs 1-3)
                starved |= {wid for wid in self._late if self._open(wid, rows[wid])}
            if starved - self.urgent:
                self.urgent |= starved
                plan = self._plan_pass(rows, now, est, flat=False)
            if any(self._open(wid, r) and wid not in plan and self._can_finish(wid, r, now) for wid, r in rows.items()):
                plan = self._plan_pass(rows, now, est, flat=True)
        self.urgent = {wid for wid in self.urgent if not rows.get(wid, {}).get("assignments") and wid in rows}
        self.plan = plan

    def _open(self, wid, r) -> bool:
        """Not delivered and not created yet (only those can be left without a slot)."""
        return not r["final_output_delivered"] and not r["assignments"] and wid not in self.placements

    def _protect(self) -> bool:
        """Stall protections (finish_h, flat_slack_h, gap_factor) always, or only once the platform has been
        measured slow: a gap between status replies longer than protect_gap_h simulated hours."""
        return self.protect_gap_h <= 0 or self.gap_h > self.protect_gap_h

    def _flat_slack(self) -> float:
        """Spare time below which a created job stops pausing: a slow platform may not let us restart it in time."""
        return max(self.flat_slack_h, self.gap_factor * self.gap_h)

    def _can_finish(self, wid, r, now: float) -> bool:
        """Could the job still be delivered in time at its fastest? Only then is running others flat out worth it."""
        w = self.W[wid]
        start = max(now, w.release_h - self.spec.boot_h)
        return start + self._run_hours(w, r, self._fastest(w), False) <= w.deadline_h

    def _plan_pass(self, rows: dict, now: float, est: dict, flat: bool) -> dict:
        self._late = set()
        h0 = int(now)
        q = self.spec.quotas
        cap = {"v": np.full(self.H + 1, q.max_vcpus, dtype=float), "n": np.full(self.H + 1, q.max_vms, dtype=float)}
        for fam, c in q.gpu_caps.items():
            cap[fam] = np.full(self.H + 1, c, dtype=float)
        jobs = []
        for wid, r in rows.items():
            w = self.W[wid]
            if r["final_output_delivered"] or (not r["assignments"] and wid in self.placements):
                continue
            if r["assignments"] and wid not in self.placements:
                self._adopt(w, r)
            created = bool(r["assignments"])
            last = min(self.H - 1, int(math.floor(w.deadline_h - self.margin_h)) - 1)
            first = h0 if created else max(h0, int(math.ceil(w.release_h - self.spec.boot_h - 1e-9)))
            # soft end: plan to finish early when that fits, so a created job does not drift to the deadline
            soft = last - self.slack_h
            old = self.plan.get(wid)
            commit = self.commit_h >= 0 and not created and old is not None and old.start <= h0 + self.commit_h
            flex = (last - first + 1) - self._run_hours(w, r, self._fastest(w, self.flex_workers), False)
            # created jobs first, then kept starts (they are about to be created), then by flexibility
            rank = 0 if created else 1 if wid in self.urgent else 2 if commit and self.commit_first else 3
            jobs.append((rank, flex, wid, created, commit, first, last, soft))
        jobs.sort()
        prev, plan = self.plan, {}
        for _c, _flex, wid, created, commit, first, last, soft in jobs:
            w, r = self.W[wid], rows[wid]
            old = prev.get(wid)
            if created:
                options = [self.placements[wid]]
            elif commit:      # keep the placement and start chosen when it was close: no postponing at the door
                options, first = [old.placement], max(h0, old.start)
            else:
                options = self._candidates(w, est)
            best = None
            for end in ([soft, last] if soft < last else [last]):
                for pl in options:
                    need = self._run_hours(w, r, pl, created)
                    lo = min(first, last)
                    if end < last and lo + math.ceil(need) - 1 > end and not created:
                        continue                  # the soft end does not fit this placement
                    b = self._best_block(w, pl, need, h0, lo, max(end, lo + math.ceil(need) - 1) if created else end,
                                         est, cap, fixed_start=created or commit,
                                         stretch=(1.0,) if created and (flat or (self._protect() and (need <= self.finish_h
                                                                        or (last - lo + 1) - need <= self._flat_slack()))) else None)
                    if b and (best is None or b[0] < best[0][0] or (not self.shift and b[1] < best[0][1])):
                        best = (b, pl)
                if best:
                    if end == last and soft < last and not created:
                        self._late.add(wid)
                    break
            if best is None and commit:       # the committed slot no longer fits: plan it afresh
                commit = False
                for pl in self._candidates(w, est):
                    b = self._best_block(w, pl, self._run_hours(w, r, pl, False), h0, max(h0, first), last,
                                         est, cap, fixed_start=False)
                    if b and (best is None or b[0] < best[0][0]):
                        best = (b, pl)
            if best is None and created:       # over its deadline or squeezed: run every hour to the end
                pl = self.placements[wid]
                end = max(h0 + 1, min(self.H, h0 + math.ceil(self._run_hours(w, r, pl, True))))
                best = ((0.0, h0, end, frozenset(range(h0, end))), pl)
            if best is None:
                continue
            (g, s, e, run), pl = best
            self._take(cap, pl, s, e)
            plan[wid] = Slot(pl, s, e, run, g, commit)
        return plan

    def _adopt(self, w, r):
        """VMs we have no record of (controller restarted): rebuild the placement from what is running."""
        zone = r["assignments"][0]["zone"]
        known = [self.vm_profile[a["vm_id"]] for a in r["assignments"] if a["vm_id"] in self.vm_profile]
        if known:
            pid = known[0]
        else:       # best guess: the most efficient suitable profile in that zone (else anywhere)
            ps = ([p for p in self.spec.profiles if p.available_in(zone) and suitable(p, w)]
                  or [p for p in self.spec.profiles if suitable(p, w)])
            pid = min(ps, key=lambda p: p.power_kw / throughput(p, w)).id
            for a in r["assignments"]:
                self.vm_profile.setdefault(a["vm_id"], pid)
        self.placements[w.id] = Placement(zone, pid, len(r["assignments"]))
        self.decisions.append({"t": round(self._last_h or 0.0, 2), "workload": w.id, "action": "adopt",
                               "reason": "existing VMs found; continuing with them", "zone": zone, "profile": pid})

    def _fastest(self, w, workers: int = 0) -> Placement:
        p = max((p for p in self.spec.profiles if suitable(p, w)), key=lambda p: throughput(p, w))
        return Placement(next(iter(p.zones)) if p.zones else self.spec.zones[0].id, p.id,
                         min(workers, w.max_workers) if workers else w.max_workers)

    # ------------------------------------------------------------ main step
    def decide(self, status: dict) -> list:
        now = status["now_h"]
        rows = {r["id"]: r for r in status["workloads"]}
        if self._last_h is not None:
            dt = max(0.0, now - self._last_h)
            for wid, r in rows.items():
                if now > self.W[wid].release_h:
                    for a in r["assignments"]:
                        if a["state"] == "running":
                            self.vm_run_h[a["vm_id"]] = self.vm_run_h.get(a["vm_id"], 0.0) + dt
        if self._last_h is not None and self.placements:      # the clock runs: how long were we blind?
            self.gap_h = max(self.gap_h, now - self._last_h)
        self._last_h = now
        hour = int(now)
        if hour != self._plan_hour:
            self._replan(rows, now)
            self._plan_hour = hour

        actions = []
        for wid, r in rows.items():
            w = self.W[wid]
            if r["final_output_delivered"]:
                if r["assignments"]:
                    ids = [a["vm_id"] for a in r["assignments"]]
                    actions += [("delete", v, wid) for v in ids]
                    self._log(now, wid, "delete", "final output delivered; deleting ends idle draw", vms=ids)
                continue
            slot = self.plan.get(wid)
            finishing = r["completed_work"] >= w.work_units - 1e-9
            if not r["assignments"]:
                if wid in self.placements:
                    continue                      # create sent this hour, not visible yet
                if slot and slot.start <= hour and (hour in slot.run or slot.commit):
                    pl = slot.placement
                    check_placement(w, self.Z[pl.zone_id])        # mandatory before any create
                    self.placements[wid] = pl
                    actions += [("create", wid, pl.zone_id, pl.profile_id, i) for i in range(pl.workers)]
                    why = (self._why(slot, hour) if hour in slot.run else
                           "start kept from the previous plan; created now, paused until its first clean hour")
                    self._log(now, wid, "create", why, zone=pl.zone_id, profile=pl.profile_id,
                              workers=pl.workers, block=[slot.start, slot.end], run_hours=len(slot.run),
                              est_kg=round(slot.grams / 1000, 3))
                elif slot:
                    self._log(now, wid, "wait", f"planned start at hour {slot.start}: cleaner or quota-free then")
                else:
                    self._log(now, wid, "blocked", "no quota or legal placement fits before the deadline")
                continue
            want = finishing or slot is None or hour in slot.run
            for a in r["assignments"]:
                if want and a["state"] == "stopped":
                    actions.append(("start", a["vm_id"], wid))
                elif not want and a["state"] == "running":
                    actions.append(("stop", a["vm_id"], wid))
            reason = "finishing output" if finishing else ("no plan: run" if slot is None else self._why(slot, hour))
            self._log(now, wid, "run" if want else "pause", reason)
        order = {"delete": 0, "stop": 1, "start": 2, "create": 3}
        return sorted(actions, key=lambda a: order[a[0]])

    def bootstrap(self, status: dict) -> list:
        """The run clock starts at the first accepted create. Create the job planned to start first now;
        it waits at idle power until its release (a few idle watt-hours)."""
        if self.placements:
            return []
        rows = {r["id"]: r for r in status["workloads"]}
        self._replan(rows, status["now_h"])
        if not self.plan:
            return []
        wid, slot = min(self.plan.items(), key=lambda kv: (kv[1].start, self.W[kv[0]].release_h))
        pl = slot.placement
        check_placement(self.W[wid], self.Z[pl.zone_id])
        self.placements[wid] = pl
        self._log(status["now_h"], wid, "create", "first create starts the run clock; earliest planned job",
                  zone=pl.zone_id, profile=pl.profile_id, workers=pl.workers, block=[slot.start, slot.end])
        return [("create", wid, pl.zone_id, pl.profile_id, i) for i in range(pl.workers)]

    def rejected(self, now: float, action: tuple, error: str):
        """The platform refused an action (quota, limits). Forget a failed create so it is re-planned."""
        if action[0] == "create":
            self.placements.pop(action[1], None)
            self.plan.pop(action[1], None)        # a committed slot is not re-committed
            self._plan_hour = None
        self._state.pop(action[1] if action[0] == "create" else action[2], None)
        self.decisions.append({"t": round(now, 2), "workload": action[1] if action[0] == "create" else action[2],
                               "action": "rejected", "reason": f"{action[0]} refused: {error}"})

    def _why(self, slot: Slot, hour: int) -> str:
        n, L = len(slot.run), slot.end - slot.start
        state = "run" if hour in slot.run else "pause"
        return f"{state}: hour {hour} {'is' if state == 'run' else 'is not'} one of the {n} cleanest of its {L}-hour block"

    def _log(self, now, wid, action, reason, **kw):
        key = action if action not in ("run", "pause") else action
        if self._state.get(wid) == key and action not in ("create", "delete"):
            return
        self._state[wid] = key
        self.decisions.append({"t": round(now, 2), "workload": wid, "action": action, "reason": reason, **kw})


# Named settings for live runs (GREENOPS_PLANNER). With no variable set the image runs DEFAULT_PROFILE, which is
# what the judges get. Practice runs 9 and 10 (adaptive) matched our best score with every safety net on.
# "run2plus" plans like practice run 2 (no soft end, no kept starts, pauses until the end) but keeps every
# protection that costs nothing on a normal run: no job may starve, the end-of-run fix, and the whole live
# loop. Offline it gains ~0.3% on a fast platform and loses the bonus on most grids when the platform is slow.
DEFAULT_PROFILE = "adaptive"
PROFILES = {
    "safe": {},                        # every safety rule always on (practice runs 7 and 8)
    "run2plus": dict(slack_h=0, commit_h=-1, finish_h=0, flat_slack_h=0, gap_factor=0),
    # run 2's planning while the platform answers quickly; default's stall protections switch on by themselves
    # once a gap between status replies exceeds 0.75 simulated hours (about 4 wall seconds at 720x)
    "adaptive": dict(slack_h=0, commit_h=-1, protect_gap_h=0.75),
}


def make_planner(spec, forecast, profile: str = DEFAULT_PROFILE) -> Planner:
    profile = DEFAULT_PROFILE if profile in ("", "default") else profile
    if profile not in PROFILES:
        raise ValueError(f"unknown planner profile {profile!r}; choose one of {sorted(PROFILES)}")
    return Planner(spec, forecast, name=f"carbon-aware/{profile}", **PROFILES[profile])
