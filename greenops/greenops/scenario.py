"""Synthetic practice scenarios that mimic the challenge description.

None of this is the organizers' data. It exists so policies can be tuned before
Friday: 15 workloads, 120 h, 11 zones in 8 countries, 20 VMs / 320 vCPUs, GPU caps,
noisy electricity forecasts. Use different seeds; never tune to one seed.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass

from .guard import DACH, EU_EEA, resolve_countries
from .model import Profile, Quotas, Workload, Zone

HORIZON_H = 120.0

ZONES = [
    Zone("ch-gva-2", "CH", 1.15), Zone("ch-dk-2", "CH", 1.2),
    Zone("de-fra-1", "DE", 1.25), Zone("de-muc-1", "DE", 1.2),
    Zone("at-vie-1", "AT", 1.2), Zone("at-vie-2", "AT", 1.15),
    Zone("bg-sof-1", "BG", 1.3), Zone("fr-par-x", "FR", 1.2),
    Zone("se-sto-x", "SE", 1.1), Zone("pl-waw-x", "PL", 1.3), Zone("it-mil-x", "IT", 1.25),
]
ALL_COUNTRIES = frozenset(z.country for z in ZONES)

# Where each zone sits on the map (city centre, approximate). Real Exoscale zones are named after
# their cities; the "-x" zones are fictional game additions, placed in a plausible city.
ZONE_SITES = {
    "ch-gva-2": (46.20, 6.14, "Geneva", True), "ch-dk-2": (47.37, 8.54, "Zurich", True),
    "de-fra-1": (50.11, 8.68, "Frankfurt", True), "de-muc-1": (48.14, 11.58, "Munich", True),
    "at-vie-1": (48.24, 16.33, "Vienna", True), "at-vie-2": (48.16, 16.45, "Vienna", True),
    "bg-sof-1": (42.70, 23.32, "Sofia", True), "fr-par-x": (48.86, 2.35, "Paris", False),
    "se-sto-x": (59.33, 18.07, "Stockholm", False), "pl-waw-x": (52.23, 21.01, "Warsaw", False),
    "it-mil-x": (45.46, 9.19, "Milan", False),
}

# rough mean grid intensity, gCO2/kWh (illustrative), and solar share for the daily dip
BASE_INTENSITY = {"CH": 45, "SE": 30, "FR": 60, "AT": 140, "DE": 380, "IT": 300, "BG": 420, "PL": 680}
SOLAR = {"CH": .15, "SE": .05, "FR": .1, "AT": .25, "DE": .35, "IT": .4, "BG": .3, "PL": .2}

PROFILES = [
    Profile("std.medium", 2, 4, 0.04, 0.015, 1.0),
    Profile("std.large", 4, 8, 0.07, 0.02, 2.0),
    Profile("cpu.xlarge", 8, 16, 0.12, 0.03, 4.0),
    Profile("cpu.2xlarge", 16, 32, 0.22, 0.05, 7.6),
    Profile("mem.2xlarge", 16, 128, 0.26, 0.06, 7.2),
    Profile("gpu.a5000", 12, 64, 0.45, 0.10, 0, 1.0, "A5000", 1, 24),
    Profile("gpu.a40", 12, 96, 0.55, 0.12, 0, 1.6, "A40", 1, 48),
    Profile("gpu.rtxpro6000", 16, 128, 0.75, 0.14, 0, 2.6, "RTXPRO6000", 1, 96),
    Profile("gpu.a40x2", 24, 192, 1.05, 0.22, 0, 3.0, "A40", 2, 48),
]
QUOTAS = Quotas(20, 320, {"RTXPRO6000": 4, "A5000": 8, "A40": 8})


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
    rnd = random.Random(seed * 7 + 1)
    W = []

    def add(i, kind, rel, dl, work, setup, out, countries, ckpt, workers=1, mem=0, gmem=0, fams=()):
        ref = work * (0.6 if kind == "gpu" else 0.05)
        W.append(Workload(f"wl-{i:02d}", kind, rel, dl, work, setup, out, frozenset(countries), ckpt,
                          workers, 0.85, mem, gmem, frozenset(fams), ref))

    # the four examples named in the challenge text
    add(1, "cpu", 0, 72, 160, 1.0, 0.5, DACH, None, 1, 8)                         # restart-sensitive model, DACH
    add(2, "cpu", rnd.uniform(10, 30), 100, 40, 0.3, 0.3, {"CH"}, 2.0)              # Swiss-only reporting
    add(3, "cpu", rnd.uniform(0, 20), 110, 600, 2.0, 1.0,                           # large-input analytics
        resolve_countries(eu_residency=True, all_countries=ALL_COUNTRIES), 3.0, 6, 16)
    add(4, "gpu", rnd.uniform(5, 25), 96, 60, 1.0, 0.5, {"DE", "AT", "CH"}, 1.0, 2, 48, 40)  # fine-tuning
    # the rest: a mix
    for i in range(5, 16):
        kind = "gpu" if rnd.random() < 0.35 else "cpu"
        rel = rnd.uniform(0, 70)
        dur = rnd.uniform(12, 50)
        dl = min(HORIZON_H, rel + dur + rnd.uniform(8, 40))
        work = (rnd.uniform(8, 40) if kind == "gpu" else rnd.uniform(30, 300))
        res = rnd.random()
        if res < 0.25:
            countries = resolve_countries(eu_residency=True, all_countries=ALL_COUNTRIES)
        elif res < 0.4:
            countries = DACH
        elif res < 0.5:
            countries = {"CH"}
        else:
            countries = ALL_COUNTRIES
        ckpt = None if rnd.random() < 0.25 else rnd.choice([0.5, 1.0, 2.0])
        add(i, kind, rel, dl, work, rnd.choice([0.2, 0.5, 1.0, 1.5]), rnd.choice([0.2, 0.5]),
            countries, ckpt, rnd.choice([1, 1, 2, 4]), rnd.choice([0, 4, 8, 16]),
            rnd.choice([0, 16, 24]) if kind == "gpu" else 0)
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
