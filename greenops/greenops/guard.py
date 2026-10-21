"""Residency guard.

A placement attempt in a forbidden country disqualifies the whole run, even if the
API rejects it. Every create call MUST go through `check_placement` first, and the
executors call it again right before the API call (defence in depth).
"""
from __future__ import annotations

from .model import Workload, Zone

EU_EEA = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})
DACH = frozenset({"DE", "AT", "CH"})


class ResidencyViolation(RuntimeError):
    pass


def resolve_countries(*, eu_residency: bool = False, countries=None, all_countries=None) -> frozenset:
    """Combine an EU-residency flag with an explicit country list.

    EU residency excludes Switzerland; explicit restrictions still apply on top.
    """
    allowed = frozenset(countries) if countries else frozenset(all_countries or [])
    if eu_residency:
        allowed = allowed & EU_EEA if allowed else EU_EEA
    return frozenset(allowed)


def is_allowed(workload: Workload, zone: Zone) -> bool:
    return bool(workload.allowed_countries) and zone.country in workload.allowed_countries


def check_placement(workload: Workload, zone: Zone) -> None:
    if not is_allowed(workload, zone):
        raise ResidencyViolation(
            f"refusing to place {workload.id} in {zone.id} ({zone.country}); "
            f"allowed: {sorted(workload.allowed_countries)}"
        )
