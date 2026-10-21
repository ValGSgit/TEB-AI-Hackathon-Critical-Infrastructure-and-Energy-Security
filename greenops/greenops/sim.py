"""Local stand-in for the GreenOps platform, so policies can be compared offline.

It mimics the mechanics in the challenge text: boot, setup (repeated after a
restart), checkpoints, final output delivery, shared quotas, idle VMs that keep
drawing power until deleted, and a residency rule that disqualifies a run.

SCORING IS A STAND-IN. The real frozen policy (20,000 base + 5,000 bonus) is only
described in prose; replace `score()` once the organizers publish the formula.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .guard import ResidencyViolation, is_allowed
from .model import RunState, VMState, WorkloadState, combined_throughput, suitable, throughput
from .scenario import Scenario

REF_INTENSITY = 300.0   # gCO2/kWh used to turn reference energy into a reference carbon budget


@dataclass
class SimVM:
    state: VMState
    phase_left: float          # hours left in boot/setup/delivery


@dataclass
class Sim:
    sc: Scenario
    dt: float = 0.25
    now: float = 0.0
    vms: dict = field(default_factory=dict)
    ws: dict = field(default_factory=dict)
    energy_kwh: float = 0.0
    carbon_g: float = 0.0
    disqualified: str = ""
    log: list = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def __post_init__(self):
        self.W = {w.id: w for w in self.sc.workloads}
        self.Z = {z.id: z for z in self.sc.zones}
        self.P = {p.id: p for p in self.sc.profiles}
        self.ws = {w.id: WorkloadState(w.id) for w in self.sc.workloads}

    # ---------- what a controller can see ----------
    def observe(self) -> RunState:
        return RunState(self.now, self.sc.horizon_h, [v.state for v in self.vms.values()], self.ws)

    # ---------- actions ----------
    def create_vm(self, workload_id: str, zone_id: str, profile_id: str) -> str:
        w, z, p = self.W[workload_id], self.Z[zone_id], self.P[profile_id]
        if not is_allowed(w, z):
            # the real platform disqualifies even a rejected attempt
            self.disqualified = f"residency: {workload_id} -> {zone_id}"
            raise ResidencyViolation(self.disqualified)
        if self.now + 1e-9 < w.release_h:
            raise ValueError(f"{workload_id} not released yet")
        if not p.available_in(zone_id) or not suitable(p, w):
            raise ValueError(f"profile {profile_id} unusable for {workload_id} in {zone_id}")
        live = list(self.vms.values())
        if len(live) + 1 > self.sc.quotas.max_vms:
            raise ValueError("VM quota")
        if sum(self.P[v.state.profile_id].vcpus for v in live) + p.vcpus > self.sc.quotas.max_vcpus:
            raise ValueError("vCPU quota")
        if p.gpu_family:
            used = sum(self.P[v.state.profile_id].gpus for v in live
                       if self.P[v.state.profile_id].gpu_family == p.gpu_family)
            if used + p.gpus > self.sc.quotas.gpu_caps.get(p.gpu_family, 0):
                raise ValueError("GPU quota")
        vid = f"vm-{next(self._ids)}"
        self.vms[vid] = SimVM(VMState(vid, workload_id, zone_id, profile_id, "booting", self.now), self.sc.boot_h)
        self.log.append((self.now, "create", vid, workload_id, zone_id, profile_id))
        return vid

    def delete_vm(self, vm_id: str) -> None:
        v = self.vms.pop(vm_id)
        ws = self.ws[v.state.workload_id]
        still = [x for x in self.vms.values() if x.state.workload_id == ws.workload_id]
        if not still and not ws.delivered:
            ws.progress = ws.checkpointed      # unsaved work is lost
        self.log.append((self.now, "delete", vm_id, v.state.workload_id))

    # ---------- time ----------
    def step(self) -> None:
        dt = self.dt
        by_w = {}
        for v in self.vms.values():
            by_w.setdefault(v.state.workload_id, []).append(v)
        for wid, vms in by_w.items():
            w, ws = self.W[wid], self.ws[wid]
            running = []
            for v in vms:
                p = self.P[v.state.profile_id]
                st = v.state
                if st.phase == "booting":
                    v.phase_left -= dt
                    if v.phase_left <= 0:
                        st.phase, v.phase_left = "setup", w.setup_h
                elif st.phase == "setup":
                    v.phase_left -= dt
                    if v.phase_left <= 0:
                        st.phase = "running"
                elif st.phase == "running":
                    running.append(v)
                power = p.idle_kw if st.phase == "done" else p.power_kw
                kwh = power * dt * self.Z[st.zone_id].pue
                self.energy_kwh += kwh
                self.carbon_g += kwh * self.sc.carbon.at(st.zone_id, self.now)
            if running and not ws.delivered:
                # all workers of a workload share one pool of work
                p = self.P[running[0].state.profile_id]
                rate = combined_throughput(throughput(p, w), min(len(running), w.max_workers), w.parallel_eff)
                ws.progress = min(w.work_units, ws.progress + rate * dt)
                if w.checkpoint_h:
                    ws.checkpointed = ws.progress if (self.now % w.checkpoint_h) < dt else ws.checkpointed
                if ws.progress >= w.work_units - 1e-9:
                    ws.checkpointed = ws.progress
                    lead = running[0]
                    lead.state.phase, lead.phase_left = "delivering", w.output_h
                    for other in running[1:]:
                        other.state.phase = "done"
            for v in vms:
                if v.state.phase == "delivering":
                    v.phase_left -= dt
                    if v.phase_left <= 0:
                        v.state.phase = "done"
                        if self.now + dt <= w.deadline_h + 1e-9:
                            ws.delivered = True
                        else:
                            ws.failed = True
        self.now += dt

    # ---------- result ----------
    def score(self) -> dict:
        if self.disqualified:
            return {"score": 0, "disqualified": self.disqualified}
        total_ref = sum(w.ref_energy_kwh for w in self.W.values())
        useful = sum(self.W[i].ref_energy_kwh for i, s in self.ws.items() if s.delivered)
        ref_carbon = useful * REF_INTENSITY
        q = ref_carbon / (ref_carbon + self.carbon_g) if useful else 0   # 0..1, never saturates
        base = 20000 * (useful / total_ref) * q
        all_done = all(s.delivered for s in self.ws.values())
        return {
            "score": round(base + (5000 if all_done else 0)),
            "delivered": sum(s.delivered for s in self.ws.values()),
            "of": len(self.ws),
            "carbon_kg": round(self.carbon_g / 1000, 1),
            "energy_kwh": round(self.energy_kwh, 1),
            "all_done_bonus": all_done,
        }
