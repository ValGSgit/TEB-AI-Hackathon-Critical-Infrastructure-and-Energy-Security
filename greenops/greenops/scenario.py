"""Practice scenarios shaped like the real challenge.

Structure comes from catalog.py (the real 15 workloads, 11 zones in 8 countries, GPU families,
quotas). Durations, release times, deadlines and electricity are random per seed, so policies
are tuned to the shape of the problem, never to one scenario. Use many seeds.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass

from .model import Profile, Quotas, Workload, Zone

from . import catalog as C

HORIZON_H = C.HORIZON_H

ZONES = [Zone(zid, cc, {"CH": 1.15, "AT": 1.15}.get(cc, 1.25)) for zid, cc, *_ in C.ZONES]
ALL_COUNTRIES = frozenset(C.COUNTRIES)

# zone id -> (lat, lon, city, real_zone) for the map views
ZONE_SITES = {zid: (lat, lon, city, real) for zid, cc, city, lat, lon, _conf, real in C.ZONES}

BASE_INTENSITY = C.BASE_INTENSITY
SOLAR = C.SOLAR_SHARE

ZONE_IDS = frozenset(z.id for z in ZONES)
_CPU = [  # ASSUMED coefficients (fictional in the game too)
    Profile("standard.medium", 2, 4, 0.04, 0.015, 1.0),
    Profile("standard.large", 4, 8, 0.07, 0.02, 2.0),
    Profile("cpu.extra-large", 8, 16, 0.12, 0.03, 4.0),
    Profile("cpu.huge", 16, 32, 0.22, 0.05, 7.6),
    Profile("memory.huge", 16, 128, 0.26, 0.06, 7.2),
]
_GPU_SPEC = {  # family -> (vCPUs, RAM GB, kW, idle kW, throughput)   ASSUMED
    "GPU2": (12, 56, 0.40, 0.09, 1.0), "GPU3": (12, 96, 0.55, 0.12, 1.6), "RTX3080Ti": (8, 32, 0.42, 0.08, 1.1),
    "A30": (12, 64, 0.30, 0.07, 1.3), "A5000": (12, 64, 0.35, 0.08, 1.2), "RTX6000Pro": (16, 128, 0.70, 0.13, 2.8),
}
_GPU = []
for fam, (vc, mem, kw, idle, thr) in _GPU_SPEC.items():
    zones = frozenset(z for z, fams in C.GPU_ZONES.items() if fam in fams)
    _GPU.append(Profile(f"gpu.{fam.lower()}", vc, mem, kw, idle, 0, thr, fam, 1, C.GPU_MEM_GB[fam], zones))
PROFILES = _CPU + _GPU
QUOTAS = Quotas(C.MAX_VMS, C.MAX_VCPUS, dict(C.GPU_CAPS))


@dataclass
class Carbon:
    """Actual hourly intensity per zone plus a forecast whose error grows with horizon."""
    actual: dict          # zone id -> list[float] per hour
    seed: int
    error_scale: float = 0.18

    def at(self, zone_id: str, t_h: float) -> float:
        series = self.actual[zone_id]
        i = min(int(t_h), len(series) - 1)
        return series[i]

    def forecast(self, zone_id: str, issued_h: float, horizon: int = 48) -> list:
        """Forecast for hours [issued, issued+horizon). Deterministic for a given issue hour."""
        rnd = random.Random(zlib.crc32(f"{self.seed}|{zone_id}|{int(issued_h)}".encode()))
        out = []
        drift = 0.0
        for k in range(horizon):
            t = int(issued_h) + k
            drift += rnd.gauss(0, self.error_scale / 6)
            err = drift * math.sqrt(k / 24 + 0.05)
            out.append(max(5.0, self.at(zone_id, t) * (1 + err)))
        return out


def make_carbon(seed: int) -> Carbon:
    rnd = random.Random(seed)
    actual = {}
    weather = {c: [rnd.gauss(0, 1) for _ in range(int(HORIZON_H) + 50)] for c in BASE_INTENSITY}
    for z in ZONES:
        base = BASE_INTENSITY[z.country]
        series, wind = [], 0.0
        for h in range(int(HORIZON_H) + 50):
            wind = 0.85 * wind + 0.15 * weather[z.country][h]          # slow wind front, shared by country
            hour = h % 24
            sun = max(0.0, math.sin(math.pi * (hour - 6) / 12))       # 06:00-18:00
            v = base * (1 - SOLAR[z.country] * sun) * (1 + 0.35 * wind) * (1 + rnd.gauss(0, 0.03))
            series.append(max(10.0, v))
        actual[z.id] = series
    return Carbon(actual, seed)


def make_workloads(seed: int) -> list:
    """The 15 real workloads (IDs, kinds, allowed countries are known); sizes and times are random per seed."""
    rnd = random.Random(seed * 7 + 1)
    W = []
    for wid, _name, kind, countries in C.WORKLOADS:
        tr = C.TRAITS.get(wid, {})
        if tr.get("late"):
            rel = rnd.uniform(55, 80)
        elif wid in ("w-01-dach-research", "w-11-dach-simulation"):
            rel = rnd.uniform(0, 12)
        else:
            rel = rnd.uniform(0, 60)
        compute_h = rnd.uniform(8, 30) if kind == "gpu" else rnd.uniform(10, 40)
        slack = rnd.uniform(10, 45)
        out_h = rnd.uniform(1.5, 3.0) if tr.get("heavy_output") else rnd.choice([0.2, 0.5])
        setup = 2.0 if tr.get("long_setup") else rnd.choice([0.3, 0.5, 1.0])
        dl = min(HORIZON_H, rel + setup + compute_h + out_h + slack)
        thr = 1.6 if kind == "gpu" else 7.6              # work sized against a mid-range profile
        work = compute_h * thr
        ckpt = None if tr.get("restart_sensitive") else tr.get("checkpoint", rnd.choice([0.5, 1.0, 2.0]))
        ref = work * (0.6 if kind == "gpu" else 0.05)
        W.append(Workload(wid, kind, rel, dl, work, setup, out_h, frozenset(countries), ckpt,
                          tr.get("workers", 1), 0.85, rnd.choice([0, 4, 8]), tr.get("gpu_mem", 0),
                          frozenset(), ref))
    return W


@dataclass
class Scenario:
    seed: int
    zones: list
    profiles: list
    workloads: list
    quotas: Quotas
    carbon: Carbon
    horizon_h: float = HORIZON_H
    boot_h: float = 0.1


def make_scenario(seed: int) -> Scenario:
    return Scenario(seed, ZONES, PROFILES, make_workloads(seed), QUOTAS, make_carbon(seed))
