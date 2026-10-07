#!/usr/bin/env python3
"""Compress a captured Naukri session and update its GitHub Actions secret."""

from __future__ import annotations

import base64
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = ROOT / "storage_state.json"
REPOSITORY = "manojfor4u/auto-apply"
SECRET_NAME = "NAUKRI_STORAGE_STATE_GZ_B64"
GITHUB_SECRET_LIMIT = 48 * 1024
CACHE_PREFIX = "srp_simjobs_reco_wdgt_"


def encode_storage_state(path: Path = STORAGE_PATH) -> tuple[str, int]:
    try:
        state: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read a valid session file at {path}.") from exc
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("cookies"), list)
        or not isinstance(state.get("origins", []), list)
    ):
        raise SystemExit("Session file is not a valid Playwright storage state.")

    for origin in state.get("origins", []):
        if not isinstance(origin, dict) or not isinstance(
            origin.get("localStorage", []), list
        ):
            raise SystemExit("Session file contains malformed origin data.")
        items = origin.get("localStorage", [])
        if any(not isinstance(item, dict) for item in items):
            raise SystemExit("Session file contains malformed local storage data.")
        origin["localStorage"] = [
            item
            for item in items
            if not str(item.get("name", "")).startswith(CACHE_PREFIX)
        ]

    compact_json = json.dumps(state, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(compact_json, compresslevel=9, mtime=0)
    encoded = base64.b64encode(compressed).decode("ascii")
    if len(encoded) >= GITHUB_SECRET_LIMIT:
        raise SystemExit(
            "Compressed session still exceeds GitHub's 48 KB secret limit. "
            "Do not paste it into GitHub; another storage method is required."
        )
    return encoded, len(compact_json)


def main() -> int:
    if shutil.which("gh") is None:
        raise SystemExit("GitHub CLI (`gh`) is required. Install it, then retry.")

    auth = subprocess.run(
        ["gh", "auth", "status", "--hostname", "github.com"],
        capture_output=True,
        text=True,
        check=False,
    )
    if auth.returncode:
        raise SystemExit(
            "GitHub CLI is not authenticated. Run `gh auth login`, then retry."
        )

    encoded, compact_size = encode_storage_state()
    result = subprocess.run(
        ["gh", "secret", "set", SECRET_NAME, "--repo", REPOSITORY],
        input=encoded,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(
            "GitHub CLI could not update the session secret. "
            f"Details: {result.stderr.strip()}"
        )

    print(
        f"Updated {SECRET_NAME} in {REPOSITORY}. "
        f"Filtered session JSON: {compact_size:,} bytes; "
        f"secret value: {len(encoded):,} characters."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
