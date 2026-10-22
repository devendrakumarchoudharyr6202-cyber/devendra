"""Apply to Naukri jobs that match profile skills (>= threshold)."""

from __future__ import annotations

import logging
import csv
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Page

from job_matcher import (
    JobCard,
    age_to_hours,
    experience_overlaps_range,
    skill_match_ratio,
)

log = logging.getLogger("naukri.jobs")

RECOMMENDED_URL = "https://www.naukri.com/mnjuser/recommendedjobs"

SEARCH_QUERIES = [
    "Data Analyst fresher",
    "Junior Data Analyst",
    "MIS Executive fresher",
    "Python Developer 0-1 years",
    "SQL Developer fresher",
    "Business Analyst Intern",
    "Data Analyst Intern",
]
DEFAULT_TARGET_TITLES = [
    "Data Analyst",
    "Junior Data Analyst",
    "MIS Executive",
    "Python Developer",
    "SQL Developer",
    "Business Analyst Intern",
    "Data Analyst Intern",
]

APPLICATION_LOG_FIELDS = (
    "date_ist",
    "job_id",
    "company",
    "title",
    "application_link",
    "status",
)
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _application_log_path() -> Path:
    configured_path = os.getenv("NAUKRI_APPLICATION_LOG_PATH", "").strip()
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parents[1] / "artifacts" / "applications.csv"


def _job_key(item: dict[str, Any]) -> str:
    job_id = str(item.get("job_id") or "").strip()
    if job_id:
        return f"id:{job_id}"
    href = str(
        item.get("href") or item.get("application_link") or ""
    ).strip().rstrip("/").lower()
    if href:
        return f"url:{href}"
    return f"title:{item.get('title', '')}|{item.get('company', '')}".lower()


def _load_application_history(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as csv_file:
        return {
            _job_key(row): row.get("status", "")
            for row in csv.DictReader(csv_file)
            if row.get("status") not in {"dry_run", ""}
        }


def _count_daily_applications(path: Path, today: date) -> int:
    if not path.exists():
        return 0
    counted_jobs: set[str] = set()
    with path.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get("status") not in {
                "submitted",
                "submission_unconfirmed",
                "pending_confirmation",
            }:
                continue
            try:
                application_date = datetime.fromisoformat(row["date_ist"]).date()
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid application date in {path}: {row.get('date_ist')!r}"
                ) from exc
            if application_date == today:
                counted_jobs.add(_job_key(row))
    return len(counted_jobs)


def _record_application(item: dict[str, Any], status: str) -> dict[str, str]:
    path = _application_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "date_ist": datetime.now(IST).isoformat(timespec="seconds"),
        "job_id": str(item.get("job_id") or ""),
        "company": str(item.get("company") or ""),
        "title": str(item.get("title") or ""),
        "application_link": str(item.get("href") or ""),
        "status": status,
    }
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=APPLICATION_LOG_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
    return row


def _scroll(page: Page, times: int = 3) -> None:
    for _ in range(times):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(700)


def collect_recommended_jobs(page: Page, limit: int = 40) -> list[dict[str, Any]]:
    page.goto(RECOMMENDED_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)
    _scroll(page, 4)
    return page.evaluate(
        """(limit) => [...document.querySelectorAll('article.jobTuple')].slice(0, limit).map(a => {
          const link = a.querySelector('a.title, a[href*="job-listings"]');
          const href = link?.href || '';
          const idMatch = href.match(/(\\d{8,})$/) || href.match(/-(\\d{10,})/);
          return {
            job_id: a.getAttribute('data-job-id') || (idMatch ? idMatch[1] : ''),
            href,
            title: link?.getAttribute('title') || link?.innerText?.trim()
              || a.querySelector('p.title')?.getAttribute('title') || '',
            company: a.querySelector('.companyWrapper span')?.getAttribute('title') || '',
            age_text: (a.querySelector('.jobTupleFooter')?.innerText || '').split('\\n')[0].trim(),
            salary_text: [...a.querySelectorAll(
              '.ni-job-tuple-icon-srp-rupee, .salary, .sal, [class*="salary"]'
            )].map(e => e.innerText.trim()).filter(Boolean).join(' '),
            experience_text: [...a.querySelectorAll(
              '.exp-wrap, [class*="experience"], [class*="exp"]'
            )].map(e => e.innerText.trim()).filter(Boolean).join(' '),
            already_applied: /\\b(already applied|you have applied|applied)\\b/i.test(a.innerText || ''),
            required_skills: [...a.querySelectorAll('ul.tags li')].map(li => li.innerText.trim()).filter(Boolean),
            source: 'recommended'
          };
        }).filter(j => j.title);""",
        limit,
    )


def collect_search_jobs(
    page: Page,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    slug = quote_plus(query).replace("+", "-").lower()
    url = (
        f"https://www.naukri.com/{slug}-jobs"
        f"?k={quote_plus(query)}&jobAge=1"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3500)
    _scroll(page, 3)
    return page.evaluate(
        """(limit) => {
          const cards = [...document.querySelectorAll('.srp-jobtuple-wrapper, article.jobTuple, .cust-job-tuple')];
          return cards.slice(0, limit).map(a => {
            const link = a.querySelector('a.title, a[href*=\"job-listings\"]');
            const href = link?.href || '';
            const idMatch = href.match(/(\\d{8,})$/) || href.match(/-(\\d{10,})/);
            const tags = [...a.querySelectorAll('ul.tags-gt li, ul.tags li, .tag-li, .dot')]
              .map(e => e.innerText.trim()).filter(t => t && t.length < 40);
            const ageEl = a.querySelector('.job-post-day, .jobTupleFooter, span.job-post-day');
            const salaryText = [...a.querySelectorAll(
              '.ni-job-tuple-icon-srp-rupee, .salary, .sal, [class*="salary"]'
            )].map(e => e.innerText.trim()).filter(Boolean).join(' ');
            const experienceText = [...a.querySelectorAll(
              '.exp-wrap, [class*="experience"], [class*="exp"]'
            )].map(e => e.innerText.trim()).filter(Boolean).join(' ');
            return {
              job_id: a.getAttribute('data-job-id') || (idMatch ? idMatch[1] : ''),
              title: link?.innerText?.trim() || a.querySelector('.title')?.innerText?.trim() || '',
              company: a.querySelector('a.comp-name, .companyInfo, span.comp-name')?.innerText?.trim() || '',
              age_text: (ageEl?.innerText || '').split('\\n')[0].trim(),
              salary_text: salaryText,
              experience_text: experienceText,
              already_applied: /\\b(already applied|you have applied|applied)\\b/i.test(a.innerText || ''),
              required_skills: tags,
              href,
              source: 'search'
            };
          }).filter(j => j.title);
        }""",
        limit,
    )


def rank_jobs(
    raw_jobs: list[dict[str, Any]],
    profile_skills: list[str],
    min_match: float,
) -> list[JobCard]:
    ranked: list[JobCard] = []
    seen: set[str] = set()
    for j in raw_jobs:
        skills = j.get("required_skills") or []
        jid = str(j.get("job_id") or j.get("href") or j.get("title") or "")
        if not skills or not jid or jid in seen:
            continue
        seen.add(jid)
        ratio = skill_match_ratio(skills, profile_skills)
        if ratio + 1e-9 < min_match:
            continue
        ranked.append(
            JobCard(
                job_id=str(j.get("job_id") or jid),
                title=j.get("title") or "",
                company=j.get("company") or "",
                age_text=j.get("age_text") or "",
                required_skills=skills,
                match_ratio=ratio,
            )
        )
    ranked.sort(key=lambda x: (x.age_hours, -x.match_ratio))
    return ranked


def _matches_target_title(title: str, target_titles: list[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    if any(
        token in normalized.split()
        for token in ("senior", "sr", "lead", "principal", "manager", "director", "head")
    ):
        return False
    return any(
        re.sub(r"[^a-z0-9]+", " ", target.lower()).strip() in normalized
        for target in target_titles
    )


def _matches_excluded_title(title: str, excluded_title_terms: list[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return any(
        re.sub(r"[^a-z0-9]+", " ", term.lower()).strip() in normalized
        for term in excluded_title_terms
        if term.strip()
    )


def _apply_on_detail(page: Page, href: str, dry_run: bool) -> tuple[bool, str]:
    if not href:
        return False, "Job detail URL unavailable"
    page.goto(href, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    body_text = page.locator("body").inner_text()
    if re.search(r"\b(already applied|you have applied|application submitted)\b", body_text, re.I):
        return False, "Already applied or application already submitted"
    btn = page.locator("#apply-button, button:has-text('Apply'), a:has-text('Apply')").first
    if not btn.count():
        log.warning("No apply button on %s", href)
        return False, "Apply button unavailable"
    text = (btn.inner_text() or "").lower()
    if "applied" in text:
        return False, "Already applied"
    if dry_run:
        log.info("DRY_RUN detail apply: %s", href)
        return False, "Dry run; application not submitted"
    btn.click()
    page.wait_for_timeout(3000)
    confirmation = page.locator("body").inner_text()
    if re.search(
        r"\b(application submitted|successfully applied|application sent|applied successfully)\b",
        confirmation,
        re.I,
    ):
        return True, "Application confirmation shown"
    applied_button = page.locator(
        "button:has-text('Applied'), a:has-text('Applied'), "
        "#apply-button:has-text('Applied')"
    )
    if applied_button.count():
        return True, "Apply control changed to Applied"
    for role in ("button", "link"):
        final_confirmation = page.get_by_role(
            role,
            name=re.compile(r"\b(continue|confirm|submit|proceed|yes|apply)\b", re.I),
        )
        if any(
            final_confirmation.nth(index).is_visible()
            for index in range(final_confirmation.count())
        ):
            return (
                False,
                "Awaiting user approval: Naukri requires another confirmation; "
                "the final submission was not clicked",
            )
    return False, "Submission could not be confirmed"


def apply_jobs(
    page: Page,
    profile_skills: list[str],
    *,
    min_match: float = 0.50,
    max_apply: int = 5,
    daily_limit: int = 50,
    experience_min_years: float = 0,
    experience_max_years: float = 5,
    require_skill_match: bool = True,
    require_target_title_match: bool = True,
    excluded_title_terms: list[str] | None = None,
    dry_run: bool = False,
    search_queries: list[str] | None = None,
    max_age_hours: int = 24,
    target_titles: list[str] | None = None,
) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    search_errors: list[str] = []
    raw.extend(collect_recommended_jobs(page))
    for q in search_queries or SEARCH_QUERIES:
        try:
            raw.extend(
                collect_search_jobs(page, q)
            )
        except Exception as exc:
            log.warning("Search failed for %s: %s", q, exc)
            search_errors.append(f"{q}: {exc}")

    log_path = _application_log_path()
    application_history = _load_application_history(log_path)
    today = datetime.now(IST).date()
    daily_count = _count_daily_applications(log_path, today)
    submission_limit = min(max_apply, max(0, daily_limit - daily_count))

    unique: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        key = _job_key(item)
        if key in seen:
            skipped.append({
                "title": item.get("title") or "(untitled)",
                "company": item.get("company") or "",
                "reason": "Duplicate listing in this run",
            })
            continue
        seen.add(key)
        unique.append(item)

    eligible: list[dict[str, Any]] = []
    for item in unique:
        title = item.get("title") or "(untitled)"
        company = item.get("company") or ""

        def skip(reason: str) -> None:
            skipped.append({"title": title, "company": company, "reason": reason})

        if _matches_excluded_title(title, excluded_title_terms or []):
            skip("Title matches an excluded term")
            continue
        if require_target_title_match and not _matches_target_title(
            title, target_titles or DEFAULT_TARGET_TITLES
        ):
            skip("Title does not match a configured target role")
            continue
        ratio = skill_match_ratio(item.get("required_skills") or [], profile_skills)
        if require_skill_match and ratio + 1e-9 < min_match:
            skip(f"Skill match below {min_match:.0%}")
            continue
        age_text = item.get("age_text") or ""
        age_hours = age_to_hours(age_text)
        if age_hours > max_age_hours:
            skip(f"Posting age missing or older than {max_age_hours} hours")
            continue
        experience_text = item.get("experience_text") or ""
        if not experience_overlaps_range(
            experience_text, experience_min_years, experience_max_years
        ):
            skip(
                "Experience requirement does not clearly include "
                f"the {experience_min_years:g}–{experience_max_years:g}-year range"
            )
            continue
        if item.get("already_applied"):
            skip("Already applied")
            continue
        history_key = _job_key(item)
        if history_key in application_history:
            skip(
                "Application already recorded as "
                f"{application_history[history_key]}"
            )
            continue
        if not company or not (item.get("href") or item.get("job_id")):
            skip("Company or application link is unavailable")
            continue
        eligible.append({
            **item,
            "match_ratio": ratio,
            "age_hours": age_hours,
        })

    eligible.sort(key=lambda item: (item["age_hours"], -item["match_ratio"]))
    selected = eligible if submission_limit > 0 else []

    log.info(
        "Jobs scanned=%d eligible=%d candidates=%d daily_count=%d daily_limit=%d submission_limit=%d",
        len(raw),
        len(eligible),
        len(selected),
        daily_count,
        daily_limit,
        submission_limit,
    )
    for job in selected:
        log.info(
            "  → %.0f%% | %s | %s @ %s",
            job["match_ratio"] * 100,
            job["age_text"],
            job["title"],
            job["company"],
        )

    submitted: list[dict[str, str]] = []
    unconfirmed: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "scanned": len(raw),
        "jobs_found": len(raw),
        "jobs_matching_criteria": len(eligible),
        "selected": [
            {
                "job_id": j.get("job_id", ""),
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "application_link": j.get("href", ""),
                "age": j.get("age_text", ""),
                "match": round(j["match_ratio"], 3),
                "skills": j.get("required_skills", []),
            }
            for j in selected
        ],
        "applied_count": 0,
        "application_attempts": 0,
        "daily_application_count": daily_count,
        "daily_application_limit": daily_limit,
        "daily_application_slots_remaining": max(0, daily_limit - daily_count),
        "applied": False,
        "applications_submitted": submitted,
        "applications_unconfirmed": unconfirmed,
        "skipped": skipped,
        "dry_run": dry_run,
        "message": "",
        "search_errors": search_errors,
    }

    if not selected:
        if eligible and submission_limit == 0:
            result["message"] = (
                "The daily application limit has been reached; no jobs were submitted."
            )
        else:
            result["message"] = (
                "No jobs met all skill, posting-age, and experience criteria."
            )
        return result

    daily_attempts = daily_count
    application_attempts = 0
    for job in selected:
        if daily_attempts >= daily_limit or application_attempts >= max_apply:
            break
        href = job.get("href") or ""
        if not href and str(job.get("job_id", "")).isdigit():
            href = f"https://www.naukri.com/job-listings-{job['job_id']}"
        job["href"] = href
        success, status = _apply_on_detail(page, href, dry_run)
        details = {
            "job_id": str(job.get("job_id") or ""),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "application_link": href,
            "date_ist": datetime.now(
                IST
            ).isoformat(timespec="seconds"),
            "reason": status,
        }
        if success:
            submitted.append(_record_application(job, "submitted"))
            daily_attempts += 1
            application_attempts += 1
        elif status.startswith("Awaiting user approval:"):
            details["status"] = "pending_confirmation"
            unconfirmed.append(details)
            _record_application(job, "pending_confirmation")
            daily_attempts += 1
            application_attempts += 1
        elif dry_run:
            details["status"] = "dry_run"
            unconfirmed.append(details)
        elif status == "Submission could not be confirmed":
            details["status"] = "submission_unconfirmed"
            unconfirmed.append(details)
            _record_application(job, "submission_unconfirmed")
            daily_attempts += 1
            application_attempts += 1
        elif status == "Apply button unavailable":
            details["status"] = "apply_unavailable"
            skipped.append(details)
            _record_application(job, "apply_unavailable")
        else:
            skipped.append(details)

    result["applied_count"] = len(submitted)
    result["application_attempts"] = application_attempts
    result["applied"] = bool(submitted)
    result["applications_submitted"] = submitted
    result["applications_unconfirmed"] = unconfirmed
    result["daily_application_count"] = daily_attempts
    result["daily_application_slots_remaining"] = max(
        0, daily_limit - daily_attempts
    )
    result["message"] = f"Confirmed {len(submitted)} submitted applications."
    log.info(result["message"])
    return result
