"""Offline stand-in for the real GreenOps game, used to test and tune the planner.

Follows the published rules from the starter kit: boot, per-worker input staging, pooled
work with sync overhead, stop/resume (no electricity while stopped, quota still held),
final output, idle draw until delete, residency disqualification, quotas.

The electricity here is SYNTHETIC (random per seed from generic country profiles). It is
practice data only: it is not, and must never be replaced by, the scenario's actual series.
Where the rules are silent we assume: active power during boot, input, compute and output;
idle power while waiting for release or after the work is done.

Score: an approximation of greenops-score-v2 built from its published constants. The real
score is computed by the platform; use this one only to compare policies.
"""
from __future__ import annotations

import itertools
import math
import random
import zlib
from dataclasses import dataclass, field

from . import catalog as C
from .guard import ResidencyViolation, is_allowed
from .model import suitable, sync_throughput, throughput
from .spec import Spec

EPS = 1e-9


# ---------------------------------------------------------------- synthetic grid
@dataclass
class SyntheticGrid:
    """Hourly gCO2e/kWh per electricity area, plus forecasts whose error grows with lead time."""
    actual: dict
    seed: int
    error: float = 0.15

    def at(self, area: str, t_h: float) -> float:
        s = self.actual[area]
        return s[min(max(int(t_h), 0), len(s) - 1)]

    def forecast(self, area: str, issued_h: float, horizon: int = 24) -> list:
        """Values for whole hours [floor(issued), floor(issued)+horizon), as the run would publish them."""
        rnd = random.Random(zlib.crc32(f"{self.seed}|{area}|{int(issued_h)}".encode()))
        out, drift = [], 0.0
        for k in range(horizon):
            drift += rnd.gauss(0, self.error / 5)
            out.append(max(5.0, self.at(area, int(issued_h) + k) * (1 + drift * math.sqrt(k / 24 + 0.05))))
        return out


def make_grid(seed: int, areas, hours: int = 150) -> SyntheticGrid:
    rnd = random.Random(seed)
    actual = {}
    for a in sorted(areas):
        base, solar = C.BASE_INTENSITY[a], C.SOLAR_SHARE[a]
        wind, series = 0.0, []
        for h in range(hours):
            wind = 0.85 * wind + 0.15 * rnd.gauss(0, 1)
            sun = max(0.0, math.sin(math.pi * ((h % 24) - 6) / 12))
            series.append(max(10.0, base * (1 - solar * sun) * (1 + 0.35 * wind) * (1 + rnd.gauss(0, 0.03))))
        actual[a] = series
    return SyntheticGrid(actual, seed)


# ---------------------------------------------------------------- game state
@dataclass
class VM:
    id: str
    workload_id: str          # "" = unbound idle infrastructure
    zone_id: str
    profile_id: str
    created_h: float
    state: str = "creating"   # creating | running | stopped   (as the work-status API reports)
    boot_left: float = 0.0
    input_left: float = 0.0
    local_work: float = 0.0   # this worker's contribution since its last checkpoint
    since_ckpt: float = 0.0


@dataclass
class WL:
    completed: float = 0.0
    lost: float = 0.0
    output_left: float | None = None   # set when compute is complete
    output_ready_h: float | None = None
    delivered_h: float | None = None
    carbon_g: float = 0.0
    energy_kwh: float = 0.0


@dataclass
class Game:
    spec: Spec
    grid: SyntheticGrid
    dt: float = 1 / 12
    now: float = 0.0
    vms: dict = field(default_factory=dict)
    disqualified: str = ""
    unbound_g: float = 0.0
    log: list = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def __post_init__(self):
        self.W = {w.id: w for w in self.spec.workloads}
        self.Z = {z.id: z for z in self.spec.zones}
        self.P = {p.id: p for p in self.spec.profiles}
        self.ws = {w: WL() for w in self.W}

    # ------------------------------------------------ the same view the live status API gives
    def status(self) -> dict:
        rows = []
        for wid, s in self.ws.items():
            rows.append({
                "id": wid, "required_work": self.W[wid].work_units, "completed_work": s.completed,
                "lost_work": s.lost, "output_ready_at": s.output_ready_h, "final_output_delivered": s.delivered_h is not None,
                "assignments": [{"vm_id": v.id, "zone": v.zone_id, "state": v.state}
                                for v in self.vms.values() if v.workload_id == wid]})
        return {"now_h": self.now, "state": "INVALIDATED" if self.disqualified else "RUNNING",
                "qualification": "DISQUALIFIED" if self.disqualified else "QUALIFIED", "workloads": rows}

    # ------------------------------------------------ actions
    def create(self, workload_id: str, zone_id: str, profile_id: str) -> str:
        w, z, p = self.W[workload_id], self.Z[zone_id], self.P[profile_id]
        if not is_allowed(w, z):
            self.disqualified = f"residency: {workload_id} -> {zone_id}"     # even a rejected attempt
            raise ResidencyViolation(self.disqualified)
        if not p.available_in(zone_id) or not suitable(p, w):
            raise ValueError(f"profile {profile_id} not usable for {workload_id} in {zone_id}")
        mine = [v for v in self.vms.values() if v.workload_id == workload_id]
        if len(mine) >= w.max_workers:
            raise ValueError("worker limit")
        self._check_quota(p)
        vid = f"vm-{next(self._ids):03d}"
        self.vms[vid] = VM(vid, workload_id, zone_id, profile_id, self.now,
                           boot_left=self.spec.pinfo[profile_id].boot_h, input_left=w.setup_h)
        self.log.append((round(self.now, 3), "create", vid, workload_id, zone_id, profile_id))
        return vid

    def _check_quota(self, p):
        q, live = self.spec.quotas, [self.P[v.profile_id] for v in self.vms.values()]
        if len(live) + 1 > q.max_vms:
            raise ValueError("VM quota")
        if sum(x.vcpus for x in live) + p.vcpus > q.max_vcpus:
            raise ValueError("vCPU quota")
        if p.gpu_family and sum(x.gpus for x in live if x.gpu_family == p.gpu_family) + p.gpus > q.gpu_caps.get(p.gpu_family, 0):
            raise ValueError("GPU quota")

    def stop(self, vm_id: str):
        v = self.vms[vm_id]
        if v.state == "running":
            v.state = "stopped"
            self.log.append((round(self.now, 3), "stop", vm_id))

    def start(self, vm_id: str):
        v = self.vms[vm_id]
        if v.state == "stopped":
            v.state = "running"
            self.log.append((round(self.now, 3), "start", vm_id))

    def delete(self, vm_id: str):
        v = self.vms.pop(vm_id)
        s, w = self.ws.get(v.workload_id), self.W.get(v.workload_id)
        if s and s.delivered_h is None and s.output_left is None:
            lose = v.local_work
            s.completed -= lose
            s.lost += lose
        self.log.append((round(self.now, 3), "delete", vm_id))

    # ------------------------------------------------ time
    def step(self):
        dt, by_w = self.dt, {}
        for v in self.vms.values():
            by_w.setdefault(v.workload_id, []).append(v)
        for wid, vms in by_w.items():
            w, s = self.W.get(wid), self.ws.get(wid)
            computing = []
            for v in vms:
                p, active = self.P[v.profile_id], False
                if v.state == "creating":
                    v.boot_left -= dt
                    active = True
                    if v.boot_left <= EPS:
                        v.state = "running"
                elif v.state == "running" and w and s.delivered_h is None and self.now + EPS >= w.release_h:
                    if s.output_left is not None:
                        active = v is vms[0]                     # one worker ships the output
                    elif v.input_left > EPS:
                        v.input_left -= dt
                        active = True
                    else:
                        computing.append(v)
                        active = True
                if v.state == "stopped":
                    kw = 0.0
                else:
                    kw = p.power_kw if active else p.idle_kw
                kwh = kw * dt * self.Z[v.zone_id].pue
                g = kwh * self.grid.at(self.spec.sites[v.zone_id].area, self.now)
                if s:
                    s.carbon_g += g
                    s.energy_kwh += kwh
                else:
                    self.unbound_g += g
            if computing and s.output_left is None:
                n = len(computing)
                for v in computing:
                    single = throughput(self.P[v.profile_id], w)
                    inc = min(sync_throughput(single, n, w.sync_overhead) / n * dt, w.work_units - s.completed)
                    s.completed += inc
                    v.local_work += inc
                    v.since_ckpt += dt
                    if w.checkpoint_h and not w.restart_from_zero and v.since_ckpt + EPS >= w.checkpoint_h:
                        v.local_work, v.since_ckpt = 0.0, 0.0
                if s.completed >= w.work_units - 1e-6:
                    s.completed = w.work_units
                    s.output_left = w.output_h
            if s and s.output_left is not None and s.delivered_h is None:
                if any(v.state == "running" for v in vms):
                    s.output_left -= dt
                    if s.output_left <= EPS:
                        s.delivered_h = self.now + dt
                        s.output_ready_h = s.delivered_h
        self.now += dt

    # ------------------------------------------------ result
    def score(self) -> dict:
        """Approximation of greenops-score-v2 (constants from rules.json; formula shape assumed)."""
        r = self.spec.rules
        if self.disqualified:
            return {"score": 0, "disqualified": self.disqualified}
        ref = r["reference_g_per_kwh"]
        total_ref = sum(w.ref_energy_kwh for w in self.W.values())
        on_time = {i: s.delivered_h is not None and s.delivered_h <= self.W[i].deadline_h + EPS for i, s in self.ws.items()}
        frac = {i: (1.0 if on_time[i] else min(1.0, s.completed / self.W[i].work_units) * 0.99) for i, s in self.ws.items()}
        carbon = sum(s.carbon_g for s in self.ws.values()) + self.unbound_g
        useful_ref = sum(self.W[i].ref_energy_kwh * frac[i] for i in self.W) or EPS
        shared = carbon / (useful_ref * ref)
        pts = 0.0
        for i, w in self.W.items():
            if frac[i] <= 0:
                continue
            local = self.ws[i].carbon_g / (w.ref_energy_kwh * frac[i] * ref)
            q = 1 / (1 + r["local_weight"] * local + r["shared_weight"] * shared)
            pts += r["base_points"] * w.ref_energy_kwh * frac[i] / total_ref * q
        all_done = all(on_time.values())
        return {"score": round(pts + (r["completion_bonus"] if all_done else 0)),
                "delivered": sum(on_time.values()), "of": len(self.W), "all_done": all_done,
                "carbon_kg": round(carbon / 1000, 3), "energy_kwh": round(sum(s.energy_kwh for s in self.ws.values()), 2),
                "lost_work": round(sum(s.lost for s in self.ws.values()), 2)}
