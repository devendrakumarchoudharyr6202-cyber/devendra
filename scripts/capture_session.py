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

import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

load_dotenv(ROOT / ".env")

from config_loader import credentials  # noqa: E402

OUT = ROOT / "storage_state.json"
LOGIN = "https://www.naukri.com/nlogin/login"
PROFILE = "https://www.naukri.com/mnjuser/profile"


def main() -> int:
    email, password = credentials()
    print("Opening browser (headed). Complete OTP/captcha if prompted…")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN)
        page.locator("#usernameField, input[type='text']").first.fill(email)
        page.locator("#passwordField, input[type='password']").first.fill(password)
        page.get_by_role("button", name="Login").click()
        print("If OTP appears, enter it in the browser window.")
        page.wait_for_url("**/mnjuser/**", timeout=300_000)
        page.goto(PROFILE)
        context.storage_state(path=str(OUT))
        browser.close()
        print(f"Saved session → {OUT}")
        print("Next, run: python scripts/set_session_secret.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
