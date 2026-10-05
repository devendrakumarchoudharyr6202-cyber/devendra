"""Apply to Naukri jobs that match profile skills (>= threshold)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Page

from job_matcher import JobCard, skill_match_ratio

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
          required_skills: [...a.querySelectorAll('ul.tags li')].map(li => li.innerText.trim()).filter(Boolean),
          source: 'recommended'
        }))""",
        limit,
    )


def collect_search_jobs(page: Page, query: str, limit: int = 20) -> list[dict[str, Any]]:
    # sort=date / freshness via naukri search URL
    url = (
        f"https://www.naukri.com/{quote_plus(query).replace('+', '-').lower()}-jobs"
        f"?k={quote_plus(query)}&experience=3&jobAge=7&nignbevent_src=jobsearchDeskGNB"
    )
    # Prefer simpler k= search which Naukri accepts
    url = (
        "https://www.naukri.com/software-developer-jobs"
        f"?k={quote_plus(query)}&experience=3&jobAge=15"
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
            return {
              job_id: a.getAttribute('data-job-id') || (idMatch ? idMatch[1] : ''),
              title: link?.innerText?.trim() || a.querySelector('.title')?.innerText?.trim() || '',
              company: a.querySelector('a.comp-name, .companyInfo, span.comp-name')?.innerText?.trim() || '',
              age_text: (ageEl?.innerText || '').split('\\n')[0].trim(),
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


def _apply_on_detail(page: Page, href: str, dry_run: bool) -> bool:
    if not href:
        return False
    page.goto(href, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    btn = page.locator("#apply-button, button:has-text('Apply'), a:has-text('Apply')").first
    if not btn.count():
        log.warning("No apply button on %s", href)
        return False
    text = (btn.inner_text() or "").lower()
    if "applied" in text:
        log.info("Already applied: %s", href)
        return False
    if dry_run:
        log.info("DRY_RUN detail apply: %s", href)
        return True
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
    return True


def apply_jobs(
    page: Page,
    profile_skills: list[str],
    *,
    min_match: float = 0.50,
    max_apply: int = 5,
    dry_run: bool = False,
    search_queries: list[str] | None = None,
) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    raw.extend(collect_recommended_jobs(page))
    for q in search_queries or SEARCH_QUERIES:
        try:
            raw.extend(collect_search_jobs(page, q))
        except Exception as exc:
            log.warning("Search failed for %s: %s", q, exc)

    ranked = rank_jobs(raw, profile_skills, min_match)
    selected = ranked[:max_apply]

    log.info(
        "Jobs scanned=%d matched>=%.0f%%=%d applying=%d",
        len(raw),
        min_match * 100,
        len(ranked),
        len(selected),
    )
    for job in selected:
        log.info(
            "  → %.0f%% | %s | %s @ %s | skills=%s",
            job.match_ratio * 100,
            job.age_text,
            job.title,
            job.company,
            job.required_skills,
        )

    result: dict[str, Any] = {
        "scanned": len(raw),
        "matched": len(ranked),
        "selected": [
            {
                "job_id": j.job_id,
                "title": j.title,
                "company": j.company,
                "age": j.age_text,
                "match": round(j.match_ratio, 3),
                "skills": j.required_skills,
            }
            for j in selected
        ],
        "applied_count": 0,
        "applied": False,
        "dry_run": dry_run,
        "message": "",
    }

    if not selected:
        result["message"] = "No jobs met the 50% required-skill match."
        return result

    # Prefer multi-apply on recommended page for jobs that came from there
    page.goto(RECOMMENDED_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    _scroll(page, 4)

    selected_ids = []
    need_detail: list[JobCard] = []
    for job in selected:
        exists = page.evaluate(
            """(jobId) => !!document.querySelector(`article.jobTuple[data-job-id="${jobId}"]`)""",
            job.job_id,
        )
        if exists and job.job_id.isdigit():
            selected_ids.append(job.job_id)
        else:
            need_detail.append(job)

    applied = 0
    if selected_ids:
        for jid in selected_ids:
            page.evaluate(
                """(jobId) => {
                  const art = document.querySelector(`article.jobTuple[data-job-id="${jobId}"]`);
                  if (!art) return false;
                  art.scrollIntoView({block:'center'});
                  const box = art.querySelector('.tuple-check-box i, .naukicon-ot-checkbox, .tuple-check-box');
                  if (!box) return false;
                  box.click();
                  return true;
                }""",
                jid,
            )
            page.wait_for_timeout(250)

        if dry_run:
            result["message"] = f"DRY_RUN: selected {len(selected_ids)} on recommended feed."
        else:
            apply_btn = page.locator("button.multi-apply-button").filter(
                has_text=re.compile(r"apply", re.I)
            )
            if not apply_btn.count():
                apply_btn = page.get_by_role(
                    "button", name=re.compile(r"apply\s+\d+\s+job", re.I)
                )
            if apply_btn.count():
                apply_btn.first.click()
                page.wait_for_timeout(4000)
                for label in ("Continue", "Apply", "OK", "Done", "Submit"):
                    btn = page.get_by_role("button", name=re.compile(rf"^{label}$", re.I))
                    if btn.count() and btn.first.is_visible():
                        try:
                            btn.first.click(timeout=2000)
                            page.wait_for_timeout(1200)
                        except Exception:
                            pass
                applied += len(selected_ids)
            else:
                log.warning("Multi-apply button missing")

    # Detail-page apply for search results not on recommended list
    for job in need_detail:
        # Rebuild href if needed
        href = ""
        for j in raw:
            if str(j.get("job_id")) == job.job_id and j.get("href"):
                href = j["href"]
                break
        if not href and job.job_id.isdigit():
            href = f"https://www.naukri.com/job-listings-{job.job_id}"
        if _apply_on_detail(page, href, dry_run):
            applied += 1

    result["applied_count"] = applied
    result["applied"] = applied > 0
    result["message"] = (
        f"Applied/attempted {applied} of {len(selected)} selected jobs."
        if not dry_run
        else f"DRY_RUN: would apply {len(selected)} jobs."
    )
    log.info(result["message"])
    return result
