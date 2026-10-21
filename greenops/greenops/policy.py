"""Scheduling policies.

A policy only sees: the public specs (zones, profiles, workloads, quotas), the
current run state, and forecasts issued up to now. It never sees actual future
carbon values (that would break the challenge rules).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .guard import check_placement, is_allowed
from .model import Quotas, RunState, combined_throughput, suitable, throughput


@dataclass
class Context:
    zones: list
    profiles: list
    workloads: list
    quotas: Quotas
    boot_h: float
    forecast: Callable      # forecast(zone_id, issued_h) -> list of hourly gCO2/kWh from issued_h
    dt: float = 0.25

    def __post_init__(self):
        self.W = {w.id: w for w in self.workloads}
        self.Z = {z.id: z for z in self.zones}
        self.P = {p.id: p for p in self.profiles}


@dataclass
class Option:
    workload_id: str
    zone_id: str
    profile_id: str
    workers: int
    duration_h: float       # boot + setup + compute + output
    draw_kw: float          # facility draw while working (all workers, incl. PUE)


class Usage:
    """Tracks quota use while a tick's decisions are being made."""

    def __init__(self, ctx: Context, state: RunState):
        self.ctx, self.vms, self.vcpus, self.gpus = ctx, 0, 0, {}
        for v in state.vms:
            self.add(ctx.P[v.profile_id])

    def add(self, p, n=1):
        self.vms += n
        self.vcpus += p.vcpus * n
        if p.gpu_family:
            self.gpus[p.gpu_family] = self.gpus.get(p.gpu_family, 0) + p.gpus * n

    def fits(self, p, n=1) -> bool:
        q = self.ctx.quotas
        if self.vms + n > q.max_vms or self.vcpus + p.vcpus * n > q.max_vcpus:
            return False
        if p.gpu_family:
            return self.gpus.get(p.gpu_family, 0) + p.gpus * n <= q.gpu_caps.get(p.gpu_family, 0)
        return True


def options_for(ctx: Context, wid: str, remaining: float, max_workers: int = 4) -> list:
    w = ctx.W[wid]
    out = []
    for z in ctx.zones:
        if not is_allowed(w, z):
            continue
        for p in ctx.profiles:
            if not p.available_in(z.id) or not suitable(p, w):
                continue
            for n in range(1, min(w.max_workers, max_workers) + 1):
                rate = combined_throughput(throughput(p, w), n, w.parallel_eff)
                dur = ctx.boot_h + w.setup_h + remaining / rate + w.output_h
                out.append(Option(wid, z.id, p.id, n, dur, p.power_kw * n * z.pue))
    return out


def _active_workloads(state: RunState) -> set:
    return {v.workload_id for v in state.vms}


def cleanup(state: RunState) -> list:
    """Delete VMs whose job is finished: idle VMs keep drawing power until deleted."""
    acts = []
    for v in state.vms:
        ws = state.workloads[v.workload_id]
        if v.phase == "done" or ws.delivered or ws.failed:
            acts.append(("delete", v.vm_id))
    return acts


class Baseline:
    """Fixed legal location (first allowed zone), start at release, lowest-energy option that meets the deadline."""
    name = "baseline"

    def decide(self, ctx: Context, state: RunState) -> list:
        acts = cleanup(state)
        use = Usage(ctx, state)
        active = _active_workloads(state)
        for w in sorted(ctx.workloads, key=lambda w: w.deadline_h):
            ws = state.workloads[w.id]
            if ws.delivered or ws.failed or w.id in active or state.now_h < w.release_h:
                continue
            opts = options_for(ctx, w.id, w.work_units - ws.progress)
            first_zone = min(o.zone_id for o in opts) if opts else None      # one fixed legal location
            on_time = [o for o in opts if o.zone_id == first_zone
                       and state.now_h + o.duration_h * 1.2 <= w.deadline_h]
            opts = sorted(on_time, key=lambda o: o.duration_h * o.draw_kw) or \
                sorted((o for o in opts if o.zone_id == first_zone), key=lambda o: o.duration_h)
            for o in opts:
                if use.fits(ctx.P[o.profile_id], o.workers):
                    acts.append(("create", o))
                    use.add(ctx.P[o.profile_id], o.workers)
                    break
        return acts


class CarbonAware:
    """Forecast-driven planner, re-planned every tick.

    For each waiting workload it looks at every legal (zone, profile, workers) option
    and every start hour up to the latest safe start, estimates carbon from the
    current forecast, and either starts now or waits for a cleaner window.
    """
    name = "carbon-aware"

    def __init__(self, safety=1.2, buffer_h=2.0, forecast_h=48, min_gain=0.03, run_hopeless=False):
        # run_hopeless: set True if Friday's scoring gives credit for partial work on late jobs
        self.safety, self.buffer_h, self.forecast_h, self.min_gain = safety, buffer_h, forecast_h, min_gain
        self.run_hopeless = run_hopeless
        self.decisions = []        # what the planner decided and why, for the UI
        self._last = {}

    def _curve(self, ctx, zone_id, now):
        f = ctx.forecast(zone_id, now)[: self.forecast_h]
        tail = sum(f[-24:]) / min(24, len(f))     # beyond the forecast: assume the last day's mean
        return f, tail

    def _window_carbon(self, curve, tail, offset_h, start_h, length_h, draw_kw):
        g, t, end = 0.0, start_h, start_h + length_h
        while t < end - 1e-9:
            step = min(1.0 - (t % 1.0), end - t)
            k = int(t - offset_h)
            g += draw_kw * step * (curve[k] if 0 <= k < len(curve) else tail)
            t += step
        return g

    def plan(self, ctx, state, wid, curves):
        w = ctx.W[wid]
        ws = state.workloads[wid]
        remaining = w.work_units - ws.progress
        now, best = state.now_h, None
        for o in options_for(ctx, wid, remaining):
            latest = w.deadline_h - o.duration_h * self.safety - self.buffer_h
            if latest < now:
                continue
            curve, tail = curves[o.zone_id]
            t = now
            while t <= latest + 1e-9:
                g = self._window_carbon(curve, tail, now, t + ctx.boot_h, o.duration_h - ctx.boot_h, o.draw_kw)
                if best is None or g < best[0] - 1e-6:
                    best = (g, t, o, latest - now)
                t = (int(t) + 1.0) if t == now else t + 1.0
        return best   # (carbon_g, start_h, option, slack_h) or None if nothing is safe any more

    def _note(self, now, wid, kind, o, t, g_best, g_now, slack):
        last = self._last.get(wid)
        if last and last[:4] == (kind, o.zone_id, o.profile_id, o.workers) and abs(last[4] - t) <= 2.0:
            return                     # only record real changes of plan, not 1-hour jitter
        self._last[wid] = (kind, o.zone_id, o.profile_id, o.workers, t)
        self.decisions.append({
            "t": now, "workload": wid, "decision": kind, "zone": o.zone_id, "profile": o.profile_id,
            "workers": o.workers, "planned_start": t, "carbon_best_g": round(g_best, 1),
            "carbon_now_g": round(g_now, 1), "slack_h": round(slack, 1)})

    def decide(self, ctx: Context, state: RunState) -> list:
        acts = cleanup(state)
        use = Usage(ctx, state)
        active = _active_workloads(state)
        curves = {z.id: self._curve(ctx, z.id, state.now_h) for z in ctx.zones}
        starts = []
        for w in ctx.workloads:
            ws = state.workloads[w.id]
            if ws.delivered or ws.failed or w.id in active or state.now_h < w.release_h:
                continue
            best = self.plan(ctx, state, w.id, curves)
            if best is None:
                # no option is safe any more: start the fastest legal option now if it can still finish
                opts = options_for(ctx, w.id, w.work_units - ws.progress)
                if opts:
                    fastest = min(opts, key=lambda o: o.duration_h)
                    if self.run_hopeless or state.now_h + fastest.duration_h <= w.deadline_h:
                        starts.append((-1.0, fastest, w.id))
                continue
            g, t, o, slack = best
            g_now = self._window_carbon(*curves[o.zone_id], state.now_h, state.now_h + ctx.boot_h,
                                        o.duration_h - ctx.boot_h, o.draw_kw)
            wait_pays = g < g_now * (1 - self.min_gain)
            start = t <= state.now_h + ctx.dt or not wait_pays
            self._note(state.now_h, w.id, "start" if start else "wait", o, t, g, g_now, slack)
            if start:
                starts.append((slack, o, w.id))
        # tightest slack first, so quotas go to the jobs that cannot wait
        for slack, o, wid in sorted(starts, key=lambda s: s[0]):
            ranked = [o] + sorted(
                (x for x in options_for(ctx, wid, ctx.W[wid].work_units - state.workloads[wid].progress)
                 if x is not o), key=lambda x: x.duration_h * x.draw_kw)
            for cand in ranked:
                p = ctx.P[cand.profile_id]
                if use.fits(p, cand.workers):
                    acts.append(("create", cand))
                    use.add(p, cand.workers)
                    break
        return acts


def apply(executor, ctx: Context, actions: list) -> None:
    for act in actions:
        if act[0] == "delete":
            executor.delete_vm(act[1])
        else:
            o = act[1]
            check_placement(ctx.W[o.workload_id], ctx.Z[o.zone_id])   # never skip this
            for _ in range(o.workers):
                executor.create_vm(o.workload_id, o.zone_id, o.profile_id)
