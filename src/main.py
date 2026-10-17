#!/usr/bin/env python3
"""Naukri agent entrypoint.

Modes:
  profile  — refresh headline/summary/key skills/resume
  resume_summary — update the scheduled summary and upload the resume
  apply    — apply to matching recommended jobs
  both     — profile then apply (default for scheduled full runs)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
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
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _profile_skill_pool(cfg: dict) -> list[str]:
    pool = list(cfg.get("core_skills") or []) + list(cfg.get("rotate_skills") or [])
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
    email, password = credentials(allow_session=True)
    agent = NaukriAgent(cfg, email, password)
    job_cfg = cfg.get("job_apply") or {}
    min_match = float(job_cfg.get("min_skill_match", 0.50))
    max_apply = int(job_cfg.get("max_apply_per_run", 5))
    daily_limit = int(job_cfg.get("max_apply_per_day", 50))
    experience_min_years = float(job_cfg.get("experience_min_years", 0))
    experience_max_years = float(job_cfg.get("experience_max_years", 5))
    require_skill_match = bool(job_cfg.get("require_skill_match", True))
    require_target_title_match = bool(
        job_cfg.get("require_target_title_match", True)
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page = agent._launch(p)
        try:
            agent._login(page)
            skills = _profile_skill_pool(cfg)
            result = apply_jobs(
                page,
                skills,
                min_match=min_match,
                max_apply=max_apply,
                daily_limit=daily_limit,
                experience_min_years=experience_min_years,
                experience_max_years=experience_max_years,
                require_skill_match=require_skill_match,
                require_target_title_match=require_target_title_match,
                dry_run=agent.dry_run,
                search_queries=job_cfg.get("search_queries"),
                max_age_hours=int(job_cfg.get("max_posting_age_hours", 24)),
                target_titles=cfg.get("target_job_titles"),
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
        choices=("profile", "resume_summary", "apply", "both"),
        default=os.getenv("NAUKRI_MODE", "both"),
    )
    args = parser.parse_args()
    cfg = load_config()

    out: dict = {
        "mode": args.mode,
        "generated_at_ist": datetime.now(IST).isoformat(timespec="seconds"),
    }
    errors: list[dict[str, str]] = []

    if args.mode in ("profile", "both"):
        try:
            email, password = credentials(allow_session=True)
            agent = NaukriAgent(cfg, email, password)
            out["profile"] = agent.run()
        except Exception as exc:
            log.exception("Profile update failed")
            errors.append({"stage": "profile", "message": str(exc)})

    if args.mode == "resume_summary":
        try:
            email, password = credentials(allow_session=True)
            agent = NaukriAgent(cfg, email, password)
            out["resume_summary"] = agent.run_resume_summary()
        except Exception as exc:
            log.exception("Profile summary update failed")
            errors.append({"stage": "profile", "message": str(exc)})

    if args.mode in ("apply", "both"):
        if (cfg.get("job_apply") or {}).get("enabled", True):
            try:
                out["apply"] = run_apply_only(cfg)
                errors.extend(
                    {"stage": "job_search", "message": message}
                    for message in out["apply"].get("search_errors", [])
                )
            except Exception as exc:
                log.exception("Job search/application run failed")
                errors.append({"stage": "job_apply", "message": str(exc)})
        else:
            out["apply"] = {"message": "Job applications are disabled in config."}

    out["errors"] = errors
    report_path = Path(__file__).resolve().parents[1] / "artifacts" / "run_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
