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


def credentials(*, allow_session: bool = False) -> tuple[str, str]:
    email = os.getenv("NAUKRI_EMAIL", "").strip()
    password = os.getenv("NAUKRI_PASSWORD", "").strip()
    has_session = any(
        os.getenv(name, "").strip()
        for name in ("NAUKRI_STORAGE_STATE_GZ_B64", "NAUKRI_STORAGE_STATE_B64")
    ) or (ROOT / "storage_state.json").is_file()
    if allow_session and has_session and (not email or not password):
        return "", ""
    if not email or not password:
        raise SystemExit(
            "Missing Naukri authentication. Set both NAUKRI_EMAIL and "
            "NAUKRI_PASSWORD, or provide an authenticated "
            "NAUKRI_STORAGE_STATE_GZ_B64, NAUKRI_STORAGE_STATE_B64, or a session "
            "file."
        )
    return email, password
