"""Normalized data model.

Everything the policy sees goes through these classes. On Friday, write a loader
(greenops/loaders.py) that maps the organizers' workload definitions, resource
catalog and zone list onto them. The policy itself should not need to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Zone:
    id: str
    country: str          # ISO code, e.g. "AT", "CH"
    pue: float = 1.2      # facility-efficiency factor (fictional in the game)


@dataclass(frozen=True)
class Profile:
    """A VM type. Throughput is work units per hour per VM for its kind of work."""
    id: str
    vcpus: int
    mem_gb: float
    power_kw: float           # draw while working
    idle_kw: float            # draw while booted but idle
    cpu_throughput: float     # work units/h for CPU workloads (0 if unsuitable)
    gpu_throughput: float = 0.0
    gpu_family: Optional[str] = None
    gpus: int = 0
    gpu_mem_gb: float = 0.0
    zones: frozenset = frozenset()   # zone ids where this profile exists; empty = all

    @property
    def is_gpu(self) -> bool:
        return self.gpus > 0

    def available_in(self, zone_id: str) -> bool:
        return not self.zones or zone_id in self.zones


@dataclass(frozen=True)
class Workload:
    id: str
    kind: str                         # "cpu" or "gpu"
    release_h: float
    deadline_h: float
    work_units: float                 # total work to do
    setup_h: float                    # paid again after every restart
    output_h: float                   # final delivery after compute
    allowed_countries: frozenset      # already resolved (EU residency, DACH, CH-only ...)
    checkpoint_h: Optional[float]     # None = restart-sensitive (all progress lost on stop)
    max_workers: int = 1
    parallel_eff: float = 0.85        # each extra worker adds this fraction of the previous one
    min_mem_gb: float = 0.0
    min_gpu_mem_gb: float = 0.0
    gpu_families: frozenset = frozenset()  # empty = any GPU family
    ref_energy_kwh: float = 1.0       # fixed reference energy used to weight the score


@dataclass(frozen=True)
class Quotas:
    max_vms: int = 20
    max_vcpus: int = 320
    gpu_caps: dict = field(default_factory=dict)   # family -> max cards


# ---------- run state (what the controller observes each tick) ----------

@dataclass
class VMState:
    vm_id: str
    workload_id: str
    zone_id: str
    profile_id: str
    phase: str            # "booting" | "setup" | "running" | "delivering" | "done"
    created_h: float


@dataclass
class WorkloadState:
    workload_id: str
    progress: float = 0.0          # work units completed
    checkpointed: float = 0.0      # work units safe from a restart
    delivered: bool = False
    failed: bool = False


@dataclass
class RunState:
    now_h: float
    horizon_h: float
    vms: list
    workloads: dict               # id -> WorkloadState


def suitable(profile: Profile, w: Workload) -> bool:
    if w.kind == "gpu":
        if not profile.is_gpu or profile.gpu_throughput <= 0:
            return False
        if w.gpu_families and profile.gpu_family not in w.gpu_families:
            return False
        if profile.gpu_mem_gb < w.min_gpu_mem_gb:
            return False
    else:
        if profile.cpu_throughput <= 0:
            return False
    return profile.mem_gb >= w.min_mem_gb


def throughput(profile: Profile, w: Workload) -> float:
    return profile.gpu_throughput if w.kind == "gpu" else profile.cpu_throughput


def combined_throughput(single: float, workers: int, eff: float) -> float:
    """Diminishing returns: 1 + eff + eff^2 + ... (synchronization overhead)."""
    return single * sum(eff ** i for i in range(workers))
