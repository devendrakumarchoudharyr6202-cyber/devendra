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

    - Core skills already present are always kept
    - Each run adds up to add_per_run missing core skills, then rotate skills
    - Each run removes up to remove_per_run non-core skills in the rotate pool
    - Clamps total into [min_total, max_total]
    """
    seed = _run_seed(now)
    protect_core = bool(policy.get("protect_core", True))
    add_n = int(policy.get("add_per_run", 1))
    remove_n = int(policy.get("remove_per_run", 1))
    min_total = int(policy.get("min_total", 10))
    max_total = int(policy.get("max_total", 25))

    norm = {s.strip().casefold(): s.strip() for s in current if s and s.strip()}
    core_norm: list[str] = []
    rotate_norm: list[str] = []
    for source, target in ((core, core_norm), (rotate, rotate_norm)):
        seen: set[str] = set()
        for skill in source:
            if skill and skill.strip() and skill.strip().casefold() not in seen:
                target.append(skill.strip())
                seen.add(skill.strip().casefold())

    core_keys = {s.casefold() for s in core_norm}
    rotate_keys = {s.casefold() for s in rotate_norm}

    desired = list(norm.values())
    desired_keys = set(norm)
    missing_core = [s for s in core_norm if s.casefold() not in norm]
    non_core = [s for s in desired if s.casefold() not in core_keys]
    removable = [s for s in non_core if s.casefold() in rotate_keys]
    to_remove: list[str] = []
    for i in range(min(remove_n, len(removable))):
        idx = _rng_index(seed, len(removable), f"remove:{i}")
        pick = removable.pop(idx)
        if pick and pick not in to_remove:
            to_remove.append(pick)

    desired = [s for s in desired if s not in to_remove]

    to_add: list[str] = []
    add_slots = add_n
    for skill in missing_core[:add_slots]:
        if skill.casefold() not in {s.casefold() for s in desired}:
            to_add.append(skill)
            desired.append(skill)
    add_slots -= len(to_add)

    desired_keys = {s.casefold() for s in desired}
    pool = [s for s in rotate_norm if s.casefold() not in desired_keys]
    for i in range(min(add_slots, len(pool))):
        idx = _rng_index(seed, len(pool), f"add:{i}")
        pick = pool.pop(idx % len(pool))
        to_add.append(pick)
        desired.append(pick)

    # Clamp size
    while len(desired) > max_total:
        candidates = [s for s in desired if s.casefold() not in core_keys]
        if not candidates:
            break
        drop = candidates[_rng_index(seed, len(candidates), f"clamp:{len(desired)}")]
        desired.remove(drop)
        if drop.casefold() not in {s.casefold() for s in to_remove}:
            to_remove.append(drop)
        to_add = [s for s in to_add if s.casefold() != drop.casefold()]

    add_slots = max(0, add_n - len(to_add))
    while len(desired) < min_total and add_slots:
        desired_keys = {s.casefold() for s in desired}
        pool = [s for s in rotate_norm if s.casefold() not in desired_keys]
        if not pool:
            break
        pick = pool[_rng_index(seed, len(pool), f"fill:{len(desired)}")]
        desired.append(pick)
        to_add.append(pick)
        add_slots -= 1

    return SkillPlan(
        keep_core=core_norm,
        add=to_add,
        remove=to_remove,
        desired=desired,
    )
