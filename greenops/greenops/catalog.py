"""What we know about the real challenge, from the organizers' public challenge guide (23 Oct 2026)
and its platform preview screenshots.

Two kinds of values live here, kept apart on purpose:
  * KNOWN: read off the guide/preview (workload IDs, names, CPU/GPU, allowed countries, GPU families
    and caps, quotas, cities on the map, phase names).
  * ASSUMED: numbers we had to invent for practice (zone IDs we could not read, GPU memory, which
    zone offers which GPU, durations). Replace them from the starter kit's resource catalog and
    workload definitions on Friday (see loaders.py).

None of this is scenario-specific future knowledge (no carbon values, no schedule), so it is allowed.
"""
from __future__ import annotations

# ---------- KNOWN: limits ----------
HORIZON_H = 120.0
MAX_VMS = 20
MAX_VCPUS = 320
GPU_CAPS = {"GPU2": 8, "GPU3": 8, "RTX3080Ti": 8, "A30": 8, "A5000": 8, "RTX6000Pro": 4}   # B300 excluded
GPU_LABELS = {"GPU2": "GPU2", "GPU3": "GPU3", "RTX3080Ti": "RTX 3080 Ti", "A30": "A30", "A5000": "A5000",
              "RTX6000Pro": "RTX 6000 Pro"}

# ---------- KNOWN: phase names used by the platform's allocation timeline ----------
PLATFORM_PHASES = {
    "waiting_release": "Waiting for release", "booting": "Booting", "setup": "Input/setup",
    "running": "Computing", "stopped": "Stopped", "done": "Idle", "delivering": "Output waiting",
}

# ---------- KNOWN cities and countries; zone IDs partly ASSUMED ----------
# id, country, city, lat, lon, id_confirmed, likely_real_exoscale_zone
ZONES = [
    ("ch-gva-2", "CH", "Geneva", 46.20, 6.14, False, True),
    ("ch-dk-2", "CH", "Zurich", 47.37, 8.54, False, True),
    ("de-fra-1", "DE", "Frankfurt", 50.11, 8.68, False, True),
    ("de-muc-1", "DE", "Munich", 48.14, 11.58, False, True),
    ("at-vie-1", "AT", "Vienna", 48.24, 16.33, True, True),     # "Vienna 1 · at-vie-1" in the preview
    ("at-vie-2", "AT", "Vienna", 48.16, 16.45, False, True),    # "Vienna ×2" on the map
    ("bg-sof-1", "BG", "Sofia", 42.70, 23.32, False, True),
    ("hr-zag-1", "HR", "Zagreb", 45.81, 15.98, False, None),
    ("it-mil-x", "IT", "Milan", 45.46, 9.19, False, False),
    ("fr-par-x", "FR", "Paris", 48.86, 2.35, False, False),
    ("es-mad-x", "ES", "Madrid", 40.42, -3.70, False, False),
]
COUNTRIES = sorted({z[1] for z in ZONES})          # AT BG CH DE ES FR HR IT  (8)

# ---------- KNOWN: the 15 workloads (ID, name, kind, allowed countries) ----------
WORKLOADS = [
    ("w-01-dach-research", "DACH serial scientific model", "cpu", ["AT", "CH", "DE"]),
    ("w-02-ch-reporting", "Swiss regulated risk calculation", "cpu", ["CH"]),
    ("w-03-med-analysis", "Mediterranean analytics", "cpu", ["ES", "IT"]),
    ("w-04-dach-batch", "Portable DACH batch", "cpu", ["AT", "CH", "DE"]),
    ("w-05-eu-render", "Parallel European rendering", "cpu", ["AT", "BG", "DE", "ES", "FR", "HR", "IT"]),
    ("w-06-large-etl", "Large-input three-country ETL", "cpu", ["DE", "HR", "IT"]),
    ("w-07-eu-training", "Cross-border GPU fine-tuning", "gpu", ["DE", "HR"]),
    ("w-08-ch-imaging", "Swiss medical GPU imaging", "gpu", ["CH"]),
    ("w-09-eu-large-model", "Cross-border large-memory GPU model", "gpu", ["DE", "HR"]),
    ("w-10-eu-visual", "Cross-border GPU visualization", "gpu", ["AT", "DE"]),
    ("w-11-dach-simulation", "Restart-sensitive DACH simulation", "cpu", ["AT", "CH", "DE"]),
    ("w-12-late-delivery", "Late European output-heavy analysis", "cpu", ["AT", "BG", "DE", "ES", "FR", "HR", "IT"]),
    ("w-13-regional-index", "Checkpointable regional search indexing", "cpu", ["AT", "DE", "HR"]),
    ("w-14-bulk-render", "Portable multi-worker media processing", "cpu", ["ES", "HR", "IT"]),
    ("w-15-heavy-archive", "Large-input archival transformation", "cpu", ["AT", "DE", "IT"]),
]
WORKLOAD_NAMES = {w[0]: w[1] for w in WORKLOADS}

# ---------- ASSUMED: traits implied by the names, used to shape practice scenarios ----------
# max_workers, restart-sensitive, long setup, late release, heavy output, min GPU memory (GB)
TRAITS = {
    "w-01-dach-research": dict(workers=1, restart_sensitive=True),              # "serial", guide: restart-sensitive
    "w-02-ch-reporting": dict(workers=1),
    "w-03-med-analysis": dict(workers=2),
    "w-04-dach-batch": dict(workers=2),
    "w-05-eu-render": dict(workers=6),                                          # "parallel"
    "w-06-large-etl": dict(workers=2, long_setup=True),                         # guide: two-hour setup
    "w-07-eu-training": dict(workers=2, gpu_mem=24),                            # guide: memory requirement
    "w-08-ch-imaging": dict(workers=1),
    "w-09-eu-large-model": dict(workers=1, gpu_mem=48),                         # "large-memory"
    "w-10-eu-visual": dict(workers=1),
    "w-11-dach-simulation": dict(workers=1, restart_sensitive=True),
    "w-12-late-delivery": dict(workers=3, late=True, heavy_output=True),
    "w-13-regional-index": dict(workers=2, checkpoint=0.5),                     # "checkpointable"
    "w-14-bulk-render": dict(workers=6),                                        # "multi-worker"
    "w-15-heavy-archive": dict(workers=2, long_setup=True),                     # "large-input"
}

# ---------- ASSUMED: GPU memory per family and which zone offers which family ----------
GPU_MEM_GB = {"GPU2": 16, "GPU3": 48, "RTX3080Ti": 12, "A30": 24, "A5000": 24, "RTX6000Pro": 96}
GPU_ZONES = {
    "ch-gva-2": ["GPU2", "A5000"], "ch-dk-2": ["GPU3", "RTX3080Ti"],
    "de-fra-1": ["GPU3", "A30", "RTX6000Pro"], "de-muc-1": ["A5000", "A30"],
    "at-vie-1": ["GPU2", "A5000", "RTX3080Ti"], "at-vie-2": ["GPU3"],
    "hr-zag-1": ["A30", "RTX6000Pro"],
}

# ---------- ASSUMED: mean grid intensity and solar share per country (illustrative, gCO2/kWh) ----------
BASE_INTENSITY = {"CH": 45, "FR": 60, "AT": 140, "ES": 150, "HR": 210, "IT": 300, "DE": 380, "BG": 420}
SOLAR_SHARE = {"CH": .15, "FR": .10, "AT": .25, "ES": .45, "HR": .25, "IT": .40, "DE": .35, "BG": .30}
