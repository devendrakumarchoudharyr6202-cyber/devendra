#!/usr/bin/env python3
"""One-time local login to capture Naukri session cookies for CI.

Usage:
  pip install -r requirements.txt
  playwright install chromium
  python scripts/capture_session.py

Then:
  python scripts/set_session_secret.py
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

OUT = ROOT / "storage_state.json"
LOGIN = "https://www.naukri.com/nlogin/login"
PROFILE = "https://www.naukri.com/mnjuser/profile"


def main() -> int:
    print(
        "Opening browser. Sign in to Naukri and complete the OTP/captcha there; "
        "do not share the code."
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(LOGIN, wait_until="domcontentloaded", timeout=90_000)
            print("Complete the full login in the browser; waiting up to 5 minutes.")
            page.wait_for_url(
                re.compile(r"naukri\.com/mnjuser/"),
                timeout=300_000,
            )
            page.goto(PROFILE, wait_until="domcontentloaded", timeout=90_000)
            if "mnjuser" not in page.url.lower() or "login" in page.url.lower():
                raise RuntimeError(
                    "Naukri did not keep the authenticated session on the profile "
                    "page. Complete login again and retry."
                )
            page.locator(
                ".resumeHeadline, .keySkills, .profileSummary"
            ).first.wait_for(state="visible", timeout=30_000)
            context.storage_state(path=str(OUT))
        finally:
            browser.close()
        print(f"Saved session → {OUT}")
        print("Next, run: python scripts/set_session_secret.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
