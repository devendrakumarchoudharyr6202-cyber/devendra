#!/usr/bin/env python3
"""Naukri agent entrypoint.

Modes:
  profile  — refresh headline/summary/resume (skills left unchanged)
  apply    — apply to matching recommended jobs
  both     — profile then apply (default for scheduled full runs)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import credentials, load_config
from job_applier import apply_jobs
from naukri_client import NaukriAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("naukri")


def _profile_skill_pool(cfg: dict, live_skills: list[str] | None = None) -> list[str]:
    pool = list(cfg.get("core_skills") or []) + list(cfg.get("rotate_skills") or [])
    if live_skills:
        pool.extend(live_skills)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in pool:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(s.strip())
    return out


def run_apply_only(cfg: dict) -> dict:
    email, password = credentials()
    agent = NaukriAgent(cfg, email, password)
    job_cfg = cfg.get("job_apply") or {}
    min_match = float(job_cfg.get("min_skill_match", 0.50))
    max_apply = int(job_cfg.get("max_apply_per_run", 5))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page = agent._launch(p)
        try:
            agent._login(page)
            live = []
            try:
                page.goto(
                    "https://www.naukri.com/mnjuser/profile",
                    wait_until="domcontentloaded",
                    timeout=90000,
                )
                page.wait_for_timeout(2500)
                live = agent._read_skills(page)
            except Exception as exc:
                log.warning("Could not read live skills (%s); using config pool", exc)
            skills = _profile_skill_pool(cfg, live)
            result = apply_jobs(
                page,
                skills,
                min_match=min_match,
                max_apply=max_apply,
                dry_run=agent.dry_run,
                search_queries=job_cfg.get("search_queries"),
            )
            agent._save_storage()
            agent._screenshot(page, "apply_done.png")
            return result
        except Exception:
            try:
                agent._screenshot(page, "apply_failure.png")
            except Exception:
                pass
            raise
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Naukri profile + job apply agent")
    parser.add_argument(
        "--mode",
        choices=("profile", "apply", "both"),
        default=os.getenv("NAUKRI_MODE", "both"),
    )
    args = parser.parse_args()
    cfg = load_config()
    email, password = credentials()

    out: dict = {"mode": args.mode}

    if args.mode in ("profile", "both"):
        agent = NaukriAgent(cfg, email, password)
        out["profile"] = agent.run()

    if args.mode in ("apply", "both"):
        out["apply"] = run_apply_only(cfg)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
