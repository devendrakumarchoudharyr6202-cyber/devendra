"""Apply to Naukri jobs that match profile skills (>= threshold)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Page

from job_matcher import age_to_hours, experience_includes_years, max_ctc_lpa, skill_match_ratio

log = logging.getLogger("naukri.jobs")

RECOMMENDED_URL = "https://www.naukri.com/mnjuser/recommendedjobs"

# Freshness-oriented searches aligned to the configured Angular/.NET profile
SEARCH_QUERIES = [
    "Senior Angular Developer",
    "Angular Developer TypeScript RxJS NgRx",
    "Senior Frontend Developer Angular",
    "Senior Full Stack Developer Angular .NET",
    ".NET Full Stack Developer ASP.NET Core",
    "Angular .NET Developer",
    "Senior Software Engineer Angular C#",
    "ASP.NET Core Web API SQL Server",
]


def _scroll(page: Page, times: int = 3) -> None:
    for _ in range(times):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(700)


def collect_recommended_jobs(page: Page, limit: int = 40) -> list[dict[str, Any]]:
    page.goto(RECOMMENDED_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)
    _scroll(page, 4)
    return page.evaluate(
        """(limit) => [...document.querySelectorAll('article.jobTuple')].slice(0, limit).map(a => ({
          job_id: a.getAttribute('data-job-id') || '',
          title: a.querySelector('p.title')?.getAttribute('title')
            || a.querySelector('p.title')?.innerText?.trim() || '',
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
        }))""",
        limit,
    )


def collect_search_jobs(page: Page, query: str, limit: int = 20) -> list[dict[str, Any]]:
    # sort=date / freshness via naukri search URL
    url = (
        f"https://www.naukri.com/{quote_plus(query).replace('+', '-').lower()}-jobs"
        f"?k={quote_plus(query)}&experience=6&jobAge=1&nignbevent_src=jobsearchDeskGNB"
    )
    # Prefer simpler k= search which Naukri accepts
    url = (
        "https://www.naukri.com/software-developer-jobs"
        f"?k={quote_plus(query)}&experience=6&jobAge=1"
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
    for label in ("Continue", "Apply", "OK", "Submit", "Done"):
        b = page.get_by_role("button", name=re.compile(rf"^{label}$", re.I))
        if b.count() and b.first.is_visible():
            try:
                b.first.click(timeout=2000)
                page.wait_for_timeout(1200)
            except Exception:
                pass
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
    return False, "Submission could not be confirmed"


def apply_jobs(
    page: Page,
    profile_skills: list[str],
    *,
    min_match: float = 0.50,
    max_apply: int = 5,
    dry_run: bool = False,
    search_queries: list[str] | None = None,
    experience_years: int = 6,
    min_ctc_lpa: float = 30.0,
    max_age_hours: int = 24,
) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    raw.extend(collect_recommended_jobs(page))
    for q in search_queries or SEARCH_QUERIES:
        try:
            raw.extend(collect_search_jobs(page, q))
        except Exception as exc:
            log.warning("Search failed for %s: %s", q, exc)

    unique: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        key = str(item.get("job_id") or item.get("href") or "")
        if not key:
            key = f"{item.get('title', '')}|{item.get('company', '')}".lower()
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

        ratio = skill_match_ratio(item.get("required_skills") or [], profile_skills)
        if ratio + 1e-9 < min_match:
            skip(f"Skill match below {min_match:.0%}")
            continue
        age_text = item.get("age_text") or ""
        age_hours = age_to_hours(age_text)
        if age_hours > max_age_hours:
            skip("Posting age missing or older than 24 hours")
            continue
        if not experience_includes_years(item.get("experience_text") or "", experience_years):
            skip(f"Experience requirement does not clearly include {experience_years}+ years")
            continue
        salary_max = max_ctc_lpa(item.get("salary_text") or "")
        if salary_max is None:
            skip("CTC not clearly disclosed")
            continue
        if salary_max <= min_ctc_lpa:
            skip(f"Maximum CTC is not above ₹{min_ctc_lpa:g} LPA")
            continue
        if item.get("already_applied"):
            skip("Already applied")
            continue
        eligible.append({
            **item,
            "match_ratio": ratio,
            "age_hours": age_hours,
            "max_ctc_lpa": salary_max,
        })

    eligible.sort(key=lambda item: (item["age_hours"], -item["match_ratio"]))
    selected = eligible[:max_apply]

    log.info(
        "Jobs scanned=%d eligible=%d applying=%d",
        len(raw),
        len(eligible),
        len(selected),
    )
    for job in selected:
        log.info(
            "  → %.0f%% | %s | %s @ %s | CTC max ₹%.1f LPA",
            job["match_ratio"] * 100,
            job["age_text"],
            job["title"],
            job["company"],
            job["max_ctc_lpa"],
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
                "age": j.get("age_text", ""),
                "match": round(j["match_ratio"], 3),
                "ctc_max_lpa": j["max_ctc_lpa"],
                "skills": j.get("required_skills", []),
            }
            for j in selected
        ],
        "applied_count": 0,
        "applied": False,
        "applications_submitted": submitted,
        "applications_unconfirmed": unconfirmed,
        "skipped": skipped,
        "dry_run": dry_run,
        "message": "",
    }

    if not selected:
        result["message"] = "No jobs met all skill, posting-age, experience, and salary criteria."
        return result

    for job in selected:
        href = job.get("href") or ""
        if not href and str(job.get("job_id", "")).isdigit():
            href = f"https://www.naukri.com/job-listings-{job['job_id']}"
        success, status = _apply_on_detail(page, href, dry_run)
        details = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "reason": status,
        }
        if success:
            submitted.append(details)
        elif dry_run or status == "Submission could not be confirmed":
            unconfirmed.append(details)
        else:
            skipped.append(details)

    result["applied_count"] = len(submitted)
    result["applied"] = bool(submitted)
    result["applications_submitted"] = submitted
    result["applications_unconfirmed"] = unconfirmed
    result["message"] = f"Confirmed {len(submitted)} submitted applications."
    log.info(result["message"])
    return result
