"""The real challenge definition, loaded from the public files vendored in ../challenge/.

These files come from the organizers' starter kit (public /api/catalog and /api/rules
projections; no electricity series). The SHA-256 of each file is checked against
manifest.json, so a stale or edited copy fails loudly.

Time is in hours since T0 = 2025-09-30T00:00Z, the start of the simulated week.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

from .guard import resolve_residency
from .model import Profile, Quotas, Workload, Zone

DIR = Path(__file__).resolve().parents[1] / "challenge"
T0 = datetime(2025, 9, 30, tzinfo=timezone.utc)
HORIZON_H = 120.0


def to_h(ts: str) -> float:
    return (datetime.fromisoformat(ts.replace("Z", "+00:00")) - T0).total_seconds() / 3600


def to_ts(h: float) -> str:
    return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Site:
    zone_id: str
    name: str
    city: str
    lat: float
    lon: float
    area: str          # electricity area used by the grid API (= country here)
    eu: bool
    fictional: bool


@dataclass(frozen=True)
class Profiles:
    """Extra per-profile facts the model.Profile does not carry."""
    family: str
    size: str
    work_unit: str
    boot_h: float
    lifecycle_kg_h: float


@dataclass
class Spec:
    scenario_id: str
    zones: list
    sites: dict          # zone id -> Site
    profiles: list
    pinfo: dict          # profile id -> Profiles
    workloads: list
    quotas: Quotas
    rules: dict          # frozen score constants (floats)
    horizon_h: float = HORIZON_H

    @property
    def boot_h(self) -> float:
        return max(i.boot_h for i in self.pinfo.values())


def _read(name: str, manifest: dict, check: bool):
    raw = (DIR / name).read_bytes()
    if check and hashlib.sha256(raw).hexdigest() != manifest["sha256"][name]:
        raise ValueError(f"{name} does not match challenge/manifest.json")
    return json.loads(raw)


def load(check: bool = True) -> Spec:
    manifest = json.loads((DIR / "manifest.json").read_text())
    cat = _read("catalog.json", manifest, check)
    wls = _read("workloads.json", manifest, check)
    rules = _read("rules.json", manifest, check)
    if not (cat["scenario_id"] == rules["scenario_id"] == manifest["scenario_id"]):
        raise ValueError("catalog, rules and manifest describe different scenarios")

    zones, sites = [], {}
    for z in cat["zones"]:
        zones.append(Zone(z["slug"], z["country"], float(z["pue"])))
        loc = z["location"]
        sites[z["slug"]] = Site(z["slug"], z["name"], loc["city"], loc["latitude"], loc["longitude"],
                                z["electricity_area"], z["eu_member"], z["fictional"])
    countries = sorted({z.country for z in zones})

    profiles, pinfo = [], {}
    for p in cat["profiles"]:
        thr = float(p["throughput"])
        per_h = thr * 3600 if p["work_unit"] == "tflop" else thr      # tflop/s -> tflop/h
        gpu = p["gpu_count"] > 0
        profiles.append(Profile(
            p["id"], p["cpu_cores"], float(p["memory_gib"]),
            float(p["active_watts"]) / 1000, float(p["idle_watts"]) / 1000,
            0.0 if gpu else per_h, per_h if gpu else 0.0,
            p["family"] if gpu else None, p["gpu_count"], float(p.get("gpu_memory_gib") or 0),
            frozenset(p["zones"])))
        pinfo[p["id"]] = Profiles(p["family"], p["size"], p["work_unit"], p["boot_seconds"] / 3600,
                                  float(p["lifecycle_kg_per_hour"]))

    r = rules["rules"]
    ref = {k: float(v) for k, v in r["reference_energy_kwh"].items()}
    workloads = []
    for w in wls:
        fams = frozenset(f for f in w["allowed_families"] if f != "cpu")
        workloads.append(Workload(
            id=w["id"], kind=w["kind"], release_h=to_h(w["release_at"]), deadline_h=to_h(w["deadline_at"]),
            work_units=float(w["required_work"]), setup_h=w["input_seconds"] / 3600,
            output_h=w["output_seconds"] / 3600,
            allowed_countries=resolve_residency(w["residency"], w.get("allowed_countries"),
                                                w.get("forbidden_countries"), countries),
            checkpoint_h=(w["checkpoint_seconds"] / 3600) or None,
            max_workers=w["max_workers"], min_gpu_mem_gb=float(w.get("minimum_gpu_memory_gib") or 0),
            gpu_families=fams, ref_energy_kwh=ref[w["id"]],
            profile_ids=frozenset(w.get("allowed_profile_ids") or ()),
            sync_overhead=float(w["sync_overhead"]), restart_from_zero=w["restart_from_zero"],
            title=w["title"]))

    quotas = Quotas(cat["max_vms"], cat["max_vcpus"], dict(cat["gpu_family_quotas"]))
    consts = {"base_points": r["base_points"], "completion_bonus": r["completion_bonus"],
              "reference_g_per_kwh": float(r["reference_gco2e_per_kwh"]),
              "local_weight": float(Fraction(r["local_weight"])), "shared_weight": float(Fraction(r["shared_weight"])),
              "version": r["version"], "hash": r["hash"]}
    return Spec(cat["scenario_id"], zones, sites, profiles, pinfo, workloads, quotas, consts)
