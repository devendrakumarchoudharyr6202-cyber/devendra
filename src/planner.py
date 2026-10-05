"""Pick summary variant + skill add/remove plan for this run."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _run_seed(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    # Stable within the same UTC hour so retries are idempotent-ish
    return now.strftime("%Y-%m-%d-%H")


def _rng_index(seed: str, n: int, salt: str = "") -> int:
    if n <= 0:
        return 0
    digest = hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) % n


def pick_summary(variants: list[str], now: datetime | None = None) -> str:
    if not variants:
        raise ValueError("summary_variants is empty in config/profile.yaml")
    seed = _run_seed(now)
    return variants[_rng_index(seed, len(variants), "summary")].strip()


def pick_headline(variants: list[str], now: datetime | None = None) -> str:
    if not variants:
        raise ValueError("headline_variants is empty in config/profile.yaml")
    seed = _run_seed(now)
    return variants[_rng_index(seed, len(variants), "headline")].strip()


@dataclass
class SkillPlan:
    keep_core: list[str]
    add: list[str]
    remove: list[str]
    desired: list[str]


def plan_skills(
    current: list[str],
    core: list[str],
    rotate: list[str],
    policy: dict[str, Any],
    now: datetime | None = None,
) -> SkillPlan:
    """Compute a gentle skill rotation.

    - Core skills are always kept
    - Each run adds up to add_per_run from rotate pool (missing ones)
    - Each run removes up to remove_per_run non-core skills
    - Clamps total into [min_total, max_total]
    """
    seed = _run_seed(now)
    protect_core = bool(policy.get("protect_core", True))
    add_n = int(policy.get("add_per_run", 1))
    remove_n = int(policy.get("remove_per_run", 1))
    min_total = int(policy.get("min_total", 10))
    max_total = int(policy.get("max_total", 25))

    norm = {s.strip(): s.strip() for s in current if s and s.strip()}
    core_norm = [s.strip() for s in core if s and s.strip()]
    rotate_norm = [s.strip() for s in rotate if s and s.strip()]

    # Always ensure core present
    desired = list(dict.fromkeys([*core_norm, *norm.keys()]))

    non_core = [s for s in desired if s not in core_norm]
    missing_rotate = [s for s in rotate_norm if s not in desired]

    # Removals: prefer non-core that are in rotate pool (safe to cycle)
    removable = [s for s in non_core if s in rotate_norm] or list(non_core)
    to_remove: list[str] = []
    for i in range(min(remove_n, len(removable))):
        if protect_core and removable[i] in core_norm:
            continue
        idx = _rng_index(seed, len(removable), f"remove:{i}")
        pick = removable.pop(idx % len(removable)) if removable else None
        if pick and pick not in to_remove:
            to_remove.append(pick)

    desired = [s for s in desired if s not in to_remove]

    # Additions
    to_add: list[str] = []
    pool = list(missing_rotate)
    for i in range(min(add_n, len(pool))):
        idx = _rng_index(seed, len(pool), f"add:{i}")
        pick = pool.pop(idx % len(pool))
        if pick not in desired and pick not in to_add:
            to_add.append(pick)
            desired.append(pick)

    # Clamp size
    while len(desired) > max_total:
        candidates = [s for s in desired if s not in core_norm]
        if not candidates:
            break
        drop = candidates[_rng_index(seed, len(candidates), f"clamp:{len(desired)}")]
        desired.remove(drop)
        if drop not in to_remove:
            to_remove.append(drop)

    while len(desired) < min_total and missing_rotate:
        pool = [s for s in rotate_norm if s not in desired]
        if not pool:
            break
        pick = pool[_rng_index(seed, len(pool), f"fill:{len(desired)}")]
        desired.append(pick)
        if pick not in to_add:
            to_add.append(pick)

    return SkillPlan(
        keep_core=core_norm,
        add=to_add,
        remove=to_remove,
        desired=desired,
    )
