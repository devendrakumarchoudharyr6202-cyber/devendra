#!/usr/bin/env python3
"""Compress a captured Naukri session and update its GitHub Actions secret."""

from __future__ import annotations

import base64
import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = ROOT / "storage_state.json"
SECRET_NAME = "NAUKRI_STORAGE_STATE_GZ_B64"
GITHUB_SECRET_LIMIT = 48 * 1024
CACHE_PREFIX = "srp_simjobs_reco_wdgt_"


def find_github_cli() -> str | None:
    executable = shutil.which("gh")
    if executable:
        return executable

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    installed_executable = program_files / "GitHub CLI" / "gh.exe"
    if installed_executable.is_file():
        return str(installed_executable)
    return None


def repository_from_origin(remote_url: str) -> str:
    if remote_url.startswith("git@"):
        host, separator, repo_path = remote_url.partition(":")
        if not separator or host.lower() != "git@github.com":
            raise SystemExit("The origin remote must point to a GitHub repository.")
    else:
        parsed = urlsplit(remote_url)
        if parsed.hostname != "github.com":
            raise SystemExit("The origin remote must point to a GitHub repository.")
        repo_path = parsed.path

    repo_path = repo_path.strip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    parts = repo_path.split("/")
    if len(parts) != 2 or not all(parts):
        raise SystemExit("Could not determine owner/repository from the origin remote.")
    return "/".join(parts)


def get_repository() -> str:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if remote.returncode or not remote.stdout.strip():
        raise SystemExit(
            "Could not read the GitHub origin remote. Configure `git remote "
            "add origin <GitHub repository URL>` and retry."
        )
    return repository_from_origin(remote.stdout.strip())


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
    gh = find_github_cli()
    if gh is None:
        raise SystemExit(
            "GitHub CLI (`gh`) is required. Install it with "
            "`winget install --id GitHub.cli --exact`, then retry."
        )

    auth = subprocess.run(
        [gh, "auth", "status", "--hostname", "github.com"],
        capture_output=True,
        text=True,
        check=False,
    )
    if auth.returncode:
        raise SystemExit(
            "GitHub CLI is not authenticated. Run "
            "`& \"$env:ProgramFiles\\GitHub CLI\\gh.exe\" auth login` "
            "in PowerShell, then retry."
        )

    repository = get_repository()
    encoded, compact_size = encode_storage_state()
    result = subprocess.run(
        [
            gh,
            "secret",
            "set",
            SECRET_NAME,
            "--repo",
            repository,
            "--body",
            encoded,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(
            "GitHub CLI could not update the session secret. "
            f"Details: {(result.stderr or result.stdout).strip()}"
        )

    print(
        f"Updated {SECRET_NAME} in {repository}. "
        f"Filtered session JSON: {compact_size:,} bytes; "
        f"secret value: {len(encoded):,} characters."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
