"""Playwright client for Naukri profile updates.

Uses system Chrome + stealth tweaks because Naukri sits behind Akamai.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from planner import pick_headline, pick_summary, plan_skills

log = logging.getLogger("naukri")

LOGIN_URL = "https://www.naukri.com/nlogin/login"
PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
HOME_URL = "https://www.naukri.com/"
ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
STORAGE_PATH = ROOT / "storage_state.json"

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""


class NaukriAgent:
    def __init__(self, cfg: dict[str, Any], email: str, password: str):
        self.cfg = cfg
        self.email = email
        self.password = password
        self.dry_run = bool(cfg.get("behavior", {}).get("dry_run", False))
        self.timeout = int(cfg.get("behavior", {}).get("timeout_ms", 60000))
        env_headless = os.getenv("HEADLESS", "").strip().lower()
        if env_headless in {"0", "false", "no"}:
            self.headless = False
        elif env_headless in {"1", "true", "yes"}:
            self.headless = True
        else:
            self.headless = bool(cfg.get("behavior", {}).get("headless", True))
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self._context: BrowserContext | None = None

    def run(self) -> dict[str, Any]:
        with sync_playwright() as p:
            browser, page = self._launch(p)
            try:
                self._assert_not_blocked(page, soft=True)
                self._login(page)
                page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(3000)
                self._assert_not_blocked(page)

                headline = pick_headline(self.cfg.get("headline_variants") or [])
                summary = pick_summary(self.cfg.get("summary_variants") or [])

                result = {
                    "headline_preview": headline[:120],
                    "summary_preview": summary[:120],
                    "resume_uploaded": False,
                    "dry_run": self.dry_run,
                }

                self._update_headline(page, headline)
                self._update_summary(page, summary)
                result["skills"] = self._update_skills(page)
                if self.cfg.get("resume", {}).get("reupload_each_run", True):
                    result["resume_uploaded"] = self._reupload_resume(page)

                self._save_storage()
                self._screenshot(page, "done.png")
                log.info("Run complete: %s", result)
                return result
            except Exception:
                try:
                    self._screenshot(page, "failure.png")
                except Exception:
                    pass
                raise
            finally:
                browser.close()

    def _launch(self, p: Playwright) -> tuple[Browser, Page]:
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "slow_mo": 80 if not self.headless else 0,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        try:
            browser = p.chromium.launch(channel="chrome", **launch_kwargs)
            log.info("Launched system Chrome (headless=%s)", self.headless)
        except Exception as exc:
            log.warning("Chrome channel unavailable (%s); falling back to Chromium", exc)
            browser = p.chromium.launch(**launch_kwargs)

        storage = self._load_storage_state()
        context = browser.new_context(
            storage_state=storage,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()
        page.set_default_timeout(self.timeout)
        self._context = context
        return browser, page

    def _load_storage_state(self) -> str | None:
        compressed_b64 = os.getenv("NAUKRI_STORAGE_STATE_GZ_B64", "").strip()
        if compressed_b64:
            encoded = re.sub(r"\s+", "", compressed_b64)
            try:
                decoded = gzip.decompress(
                    base64.b64decode(encoded, validate=True)
                )
                state = json.loads(decoded)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "NAUKRI_STORAGE_STATE_GZ_B64 could not be decoded as "
                    "compressed session JSON. Recreate it with "
                    "scripts/set_session_secret.py."
                ) from exc
            return self._write_storage_state(state, "NAUKRI_STORAGE_STATE_GZ_B64")

        b64 = os.getenv("NAUKRI_STORAGE_STATE_B64", "").strip()
        if b64:
            encoded = re.sub(r"\s+", "", b64)
            if len(encoded) % 4 == 1:
                raise RuntimeError(
                    "NAUKRI_STORAGE_STATE_B64 is not valid Base64. Re-create "
                    "the secret from storage_state.json and paste the complete "
                    "Base64 value without quotes."
                )
            encoded += "=" * (-len(encoded) % 4)
            try:
                decoded = base64.b64decode(encoded, validate=True)
                state = json.loads(decoded)
            except (ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "NAUKRI_STORAGE_STATE_B64 could not be decoded as session "
                    "JSON. Replace it with Base64 of the complete "
                    "storage_state.json file."
                ) from exc
            return self._write_storage_state(state, "NAUKRI_STORAGE_STATE_B64")
        if STORAGE_PATH.exists():
            log.info("Loaded local storage_state.json")
            return str(STORAGE_PATH)
        return None

    @staticmethod
    def _write_storage_state(state: Any, source: str) -> str:
        if not isinstance(state, dict) or not isinstance(
            state.get("cookies"), list
        ) or not isinstance(state.get("origins", []), list):
            raise RuntimeError(
                f"{source} decoded, but is not a Playwright storage state. "
                "Re-create the secret from storage_state.json."
            )
        path = ARTIFACTS / "storage_state.from_secret.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        log.info("Loaded storage state from %s", source)
        return str(path)

    def _save_storage(self) -> None:
        if self._context is None:
            return
        self._context.storage_state(path=str(STORAGE_PATH))
        log.info("Saved session → %s", STORAGE_PATH)

    def _assert_not_blocked(self, page: Page, soft: bool = False) -> None:
        try:
            content = page.content()
        except Exception:
            return
        blocked = (
            "Access Denied" in content
            or "errors.edgesuite.net" in content
            or "Permission to access" in content
        )
        if blocked:
            self._screenshot(page, "access_denied.png")
            msg = (
                "Naukri/Akamai blocked this browser (Access Denied). "
                "Retry headed locally (HEADLESS=0) or capture a fresh session."
            )
            if soft:
                log.warning(msg)
                return
            raise RuntimeError(msg)

    def _is_logged_in(self, page: Page) -> bool:
        if "Access Denied" in (page.title() or ""):
            return False
        url = page.url.lower()
        if "nlogin" in url or "/login" in url:
            return False
        try:
            body = page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        if "Access Denied" in body:
            return False
        return any(
            k in body
            for k in ("Resume headline", "Key skills", "Profile summary", "Career profile")
        )

    def _login(self, page: Page) -> None:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)
        self._dismiss_overlays(page)

        page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)
        self._assert_not_blocked(page)

        if self._is_logged_in(page):
            log.info("Already logged in via session")
            return

        if not self.email or not self.password:
            raise RuntimeError(
                "Saved Naukri session is missing or expired. Refresh "
                "NAUKRI_STORAGE_STATE_GZ_B64, NAUKRI_STORAGE_STATE_B64, or "
                "storage_state.json, or configure "
                "NAUKRI_EMAIL and NAUKRI_PASSWORD."
            )

        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)
        self._assert_not_blocked(page)
        self._dismiss_overlays(page)

        email_box = page.locator(
            "#usernameField, input[type='text'][placeholder*='Email'], "
            "input[placeholder*='Email ID']"
        ).first
        pass_box = page.locator("#passwordField, input[type='password']").first
        email_box.wait_for(state="visible", timeout=30000)
        email_box.click()
        email_box.fill(self.email)
        page.wait_for_timeout(300)
        pass_box.click()
        pass_box.fill(self.password)
        page.wait_for_timeout(300)
        page.get_by_role("button", name=re.compile(r"login", re.I)).first.click()
        page.wait_for_timeout(5000)

        err = page.locator("text=Invalid details")
        if err.count() and err.first.is_visible():
            self._screenshot(page, "login_invalid.png")
            raise RuntimeError(
                "Naukri rejected email/password (Invalid details). "
                "Update NAUKRI_PASSWORD in .env and retry."
            )

        otp_heading = page.get_by_text(
            re.compile(r"^(enter otp|otp verification|verify with otp)", re.I)
        )
        otp_input = page.locator(
            "input[placeholder*='OTP' i], input[name*='otp' i], #otpField"
        )
        if (otp_heading.count() and otp_heading.first.is_visible()) or (
            otp_input.count() and otp_input.first.is_visible()
        ):
            if self.headless:
                self._screenshot(page, "login_otp.png")
                raise RuntimeError(
                    "OTP required. Re-run with HEADLESS=0 and enter OTP in the browser."
                )
            log.info("OTP detected — waiting up to 3 minutes for you to enter it…")
            page.wait_for_url(
                re.compile(r"mnjuser|naukri\.com/(?!nlogin)"),
                timeout=180_000,
            )

        page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)
        self._assert_not_blocked(page)
        if not self._is_logged_in(page) and "login" in page.url.lower():
            self._screenshot(page, "login_blocked.png")
            raise RuntimeError("Login failed. Check credentials or complete OTP.")
        self._save_storage()
        log.info("Login succeeded")

    def _dismiss_overlays(self, page: Page) -> None:
        for label in ("ACCEPT ALL", "Accept All", "Accept", "Got it", "Close"):
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                try:
                    btn.first.click(timeout=2000)
                except Exception:
                    pass

    def _open_widget_editor(self, page: Page, title: str, root_selector: str | None = None) -> bool:
        # Dismiss leftover modals
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except Exception:
            pass

        try:
            ql = page.locator(".quickLink span.text", has_text=re.compile(rf"^{re.escape(title)}$"))
            if ql.count():
                ql.first.click(timeout=3000)
                page.wait_for_timeout(1500)
        except Exception:
            pass

        # Wait for the real widget title (not quick-link text)
        try:
            page.locator(
                f"span.widgetTitle:text-is('{title}')"
            ).first.wait_for(state="visible", timeout=8000)
        except Exception:
            log.warning("Widget title not visible: %s", title)

        opened = page.evaluate(
            """({ title, rootSelector }) => {
              const titles = [...document.querySelectorAll('span.widgetTitle')]
                .filter(e => e.textContent.trim() === title && !e.closest('.quickLink'));
              const el = titles[0];
              if (!el) return 'missing-title';
              el.scrollIntoView({block: 'center'});
              const root = (rootSelector && el.closest(rootSelector))
                || el.closest('.resumeHeadline, .keySkills, .profileSummary, .card')
                || el.parentElement?.parentElement;
              if (!root) return 'missing-root';
              const edit = root.querySelector('span.edit.icon, span.edit');
              if (!edit) return 'missing-edit:' + (root.className || '');
              edit.click();
              return 'ok';
            }""",
            {"title": title, "rootSelector": root_selector},
        )
        log.info("Open editor '%s' → %s", title, opened)
        if opened == "ok":
            page.wait_for_timeout(1500)
            return True
        return False

    def _click_save(self, page: Page) -> bool:
        save = page.get_by_role("button", name=re.compile(r"^save$", re.I))
        if save.count():
            save.first.click()
            page.wait_for_timeout(2000)
            return True
        btn = page.locator("button:has-text('Save')")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2000)
            return True
        return False

    def _read_skills(self, page: Page) -> list[str]:
        skills = page.evaluate(
            """() => [...document.querySelectorAll('.keySkills span.chip')]
              .map(e => (e.getAttribute('title') || e.textContent || '').trim())
              .filter(t => t && t.length < 40 && !/edit|key skills|cross/i.test(t))"""
        )
        deduped = list(dict.fromkeys(skills or []))
        log.info("Read %d skills from profile", len(deduped))
        return deduped

    def _update_skills(self, page: Page) -> dict[str, Any]:
        current = self._read_skills(page)
        plan = plan_skills(
            current=current,
            core=self.cfg.get("core_skills") or [],
            rotate=self.cfg.get("rotate_skills") or [],
            policy=self.cfg.get("skill_policy") or {},
        )
        changes = {"added": plan.add, "removed": plan.remove}
        if not plan.add and not plan.remove:
            return {**changes, "dry_run": self.dry_run}

        if self.dry_run:
            log.info("DRY_RUN: planned key skill changes: %s", changes)
            return {**changes, "dry_run": True}

        if not self._open_widget_editor(page, "Key Skills", ".keySkills"):
            self._screenshot(page, "skills_skip.png")
            raise RuntimeError("Could not open the Naukri key skills editor")

        for skill in plan.remove:
            removed = page.evaluate(
                """skill => {
                  const normalize = value => value.trim().toLocaleLowerCase();
                  const chip = [...document.querySelectorAll('.keySkills span.chip')]
                    .find(el => normalize(el.getAttribute('title') || el.textContent || '') === normalize(skill));
                  if (!chip) return 'missing-chip';
                  const remove = chip.querySelector(
                    'button, [role="button"], [aria-label*="remove" i], ' +
                    'i[class*="close" i], i[class*="cross" i], ' +
                    'span[class*="close" i], span[class*="cross" i], .remove'
                  );
                  if (!remove) return 'missing-remove-control';
                  remove.click();
                  return 'ok';
                }""",
                skill,
            )
            if removed != "ok":
                raise RuntimeError(
                    f"Could not remove configured key skill {skill!r}: {removed}"
                )

        skill_input = page.locator(
            "#keySkillSugg, input[placeholder*='skill' i]"
        ).first
        if plan.add and not skill_input.count():
            self._screenshot(page, "skills_skip.png")
            raise RuntimeError("Key skills editor input was not found")

        for skill in plan.add:
            skill_input.fill(skill)
            page.wait_for_timeout(500)
            option = page.locator(".sugCont li, [role='option']").filter(
                has_text=re.compile(rf"^\s*{re.escape(skill)}\s*$", re.I)
            )
            if option.count():
                option.first.click()
            else:
                skill_input.press("Enter")
            page.wait_for_timeout(250)

        if not self._click_save(page):
            self._screenshot(page, "skills_skip.png")
            raise RuntimeError("Save button not found for key skills")

        updated = {skill.casefold() for skill in self._read_skills(page)}
        missing = [skill for skill in plan.add if skill.casefold() not in updated]
        still_present = [
            skill for skill in plan.remove if skill.casefold() in updated
        ]
        if missing or still_present:
            raise RuntimeError(
                "Key skills save could not be verified "
                f"(missing additions: {missing}, remaining removals: {still_present})"
            )

        log.info("Key skills updated: %s", changes)
        return {**changes, "dry_run": False}

    def _update_headline(self, page: Page, headline: str) -> None:
        log.info("Updating resume headline (%d chars)", len(headline))
        if not self._open_widget_editor(page, "Resume headline", ".resumeHeadline"):
            log.warning("Could not open resume headline editor")
            self._screenshot(page, "headline_skip.png")
            return
        box = page.locator("#resumeHeadlineTxt")
        if not box.count():
            log.warning("Headline textarea missing")
            return
        box.fill(headline[:250])
        if self.dry_run:
            log.info("DRY_RUN: not saving headline")
            page.keyboard.press("Escape")
            return
        if self._click_save(page):
            log.info("Headline saved")
        else:
            log.warning("Save not found for headline")

    def _update_summary(self, page: Page, summary: str) -> None:
        log.info("Updating profile summary (%d chars)", len(summary))
        if not self._open_widget_editor(page, "Profile summary"):
            log.warning("Could not open summary editor — skipping")
            self._screenshot(page, "summary_skip.png")
            return
        box = page.locator("#profileSummaryTxt")
        if not box.count():
            log.warning("No textarea for summary")
            return
        box.fill(summary[:1000])
        if self.dry_run:
            log.info("DRY_RUN: not saving summary")
            page.keyboard.press("Escape")
            return
        if self._click_save(page):
            log.info("Summary saved")
        else:
            log.warning("Save button not found for summary")

    def _reupload_resume(self, page: Page) -> bool:
        resume_rel = self.cfg.get("resume", {}).get("path", "assets/resume.pdf")
        resume_path = Path(resume_rel)
        if not resume_path.is_absolute():
            resume_path = ROOT / resume_path
        if not resume_path.exists():
            log.warning("Resume file missing at %s — skip upload", resume_path)
            return False

        log.info("Re-uploading resume: %s", resume_path)
        try:
            page.locator(".quickLink span.text", has_text="Resume").first.click(timeout=3000)
            page.wait_for_timeout(800)
        except Exception:
            pass

        file_input = page.locator("#attachCV, #fileUpload, input[type='file']")
        if not file_input.count():
            log.warning("No file input found for resume")
            self._screenshot(page, "resume_skip.png")
            return False

        if self.dry_run:
            log.info("DRY_RUN: not uploading resume")
            return False

        file_input.first.set_input_files(str(resume_path))
        page.wait_for_timeout(5000)
        confirm = page.get_by_role("button", name=re.compile(r"save|update|submit|yes", re.I))
        if confirm.count():
            try:
                confirm.first.click(timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(2000)
        log.info("Resume upload attempted")
        return True

    def _screenshot(self, page: Page, name: str) -> None:
        path = ARTIFACTS / name
        page.screenshot(path=str(path), full_page=True)
        log.info("Screenshot → %s", path)
