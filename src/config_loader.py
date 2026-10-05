"""Load profile config and environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "profile.yaml"


def load_config() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Env overrides
    if os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}:
        cfg.setdefault("behavior", {})["dry_run"] = True
    if os.getenv("RESUME_PATH"):
        cfg.setdefault("resume", {})["path"] = os.getenv("RESUME_PATH")
    return cfg


def credentials() -> tuple[str, str]:
    email = os.getenv("NAUKRI_EMAIL", "").strip()
    password = os.getenv("NAUKRI_PASSWORD", "").strip()
    if not email or not password:
        raise SystemExit(
            "Missing NAUKRI_EMAIL / NAUKRI_PASSWORD. "
            "Copy .env.example → .env or set GitHub Actions secrets."
        )
    return email, password
