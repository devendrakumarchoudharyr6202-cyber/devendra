"""Skill match scoring for Naukri job required skills."""

from __future__ import annotations

import re
from dataclasses import dataclass


ALIASES: dict[str, set[str]] = {
    "java": {"java", "core java"},
    "mysql": {"mysql", "my sql"},
    "jira": {"jira", "atlassian jira"},
    "azure devops": {
        "azure devops",
        "azure boards",
        "azure devops boards",
        "ado",
    },
    "playwright": {"playwright", "playwright automation", "playwright testing"},
    "bdd": {"bdd", "behavior driven development", "behaviour driven development"},
    "cucumber": {"cucumber", "bdd-cucumber", "bdd cucumber"},
    "gherkin": {"gherkin", "gherkin syntax"},
    "page object model": {
        "page object model",
        "pom",
        "page object model (pom)",
        "page objects",
    },
    "manual testing": {"manual testing", "manual qa", "manual test"},
    "functional testing": {"functional testing", "functional qa", "functional test"},
    "regression testing": {"regression testing", "regression"},
    "integration testing": {"integration testing", "integration test"},
    "unit testing": {"unit testing", "unit test"},
    "compatibility testing": {"compatibility testing", "compat testing"},
    "web application testing": {
        "web application testing",
        "web testing",
        "web app testing",
    },
    "mobile application testing": {
        "mobile application testing",
        "mobile testing",
        "mobile qa",
    },
    "defect reporting": {
        "defect reporting",
        "bug reporting",
        "defect/bug reporting",
        "bug tracking",
    },
    "test case design": {"test case design", "test design", "testcase design"},
    "test case execution": {"test case execution", "test execution"},
    "stlc": {"stlc", "software testing life cycle"},
    "sdlc": {"sdlc", "software development life cycle"},
    "browserstack": {"browserstack", "browser stack"},
    "testim": {"testim", "testim.io"},
    "testsigma": {"testsigma"},
    "jenkins": {"jenkins", "jenkins ci"},
    "github actions": {"github actions", "github action"},
    "azure pipelines": {"azure pipelines", "azure pipeline"},
    "git": {"git", "git version control"},
    "github": {"github", "github repository", "github repo"},
    "ai testing": {"ai testing", "artificial intelligence testing"},
    "generative ai testing": {
        "generative ai testing",
        "genai testing",
        "gen ai testing",
    },
    "llm testing": {"llm testing", "large language model testing"},
    "prompt testing": {"prompt testing", "prompt validation"},
    "chatbot testing": {"chatbot testing", "chat bot testing"},
    "ai test automation": {"ai test automation", "ai-powered test automation"},
    "openai api": {"openai api", "openai api testing"},
    "machine learning testing": {
        "machine learning testing",
        "ml testing",
    },
    "responsible ai testing": {
        "responsible ai testing",
        "responsible artificial intelligence testing",
    },
    "ai response validation": {
        "ai response validation",
        "llm response validation",
        "response validation",
    },
    "acceptance criteria validation": {
        "acceptance criteria validation",
        "acceptance criteria",
        "acceptance testing",
    },
    "jmeter": {"jmeter", "apache jmeter"},
    "performance testing": {
        "performance testing",
        "perf testing",
        "performance test",
        "load testing",
    },
}


def normalize_skill(skill: str) -> str:
    s = skill.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("c/c++", "c++")
    for canonical, aliases in ALIASES.items():
        if s in aliases or s == canonical:
            return canonical
    return s


def expand_profile(skills: list[str]) -> set[str]:
    out: set[str] = set()
    for skill in skills:
        n = normalize_skill(skill)
        out.add(n)
        for canonical, aliases in ALIASES.items():
            if n == canonical or n in aliases:
                out.add(canonical)
                out |= aliases
    return out


def skill_match_ratio(required: list[str], profile_skills: list[str]) -> float:
    """Fraction of required skills covered by the profile (0..1)."""
    req = [r for r in (normalize_skill(x) for x in required) if r]
    # de-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for r in req:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    if not uniq:
        return 0.0
    profile = expand_profile(profile_skills)
    matched = 0
    for r in uniq:
        if r in profile:
            matched += 1
            continue
        # Soft containment only for longer tokens (avoid 'c' matching 'driving')
        if len(r) >= 4 and any(
            (r in p or p in r) for p in profile if len(p) >= 4
        ):
            matched += 1
    return matched / len(uniq)


def age_to_hours(age_text: str) -> int:
    """Lower = newer. Unknown ages sort last."""
    s = (age_text or "").strip().lower()
    if not s:
        return 10_000
    if "just" in s or "today" in s or "few hours" in s or "minute" in s:
        return 0
    m = re.search(r"(\d+)\s*(hour|hr|hrs|day|days|week|weeks|month|months)", s)
    if not m:
        return 10_000
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("hour") or unit.startswith("hr"):
        return n
    if unit.startswith("day"):
        return n * 24
    if unit.startswith("week"):
        return n * 24 * 7
    if unit.startswith("month"):
        return n * 24 * 30
    return 10_000


def max_ctc_lpa(salary_text: str) -> float | None:
    """Return the clearly stated maximum annual CTC in LPA, if parseable."""
    text = (salary_text or "").lower().replace(",", "").replace("₹", " ")
    unit_pattern = r"(lpa|lacs?|lakhs?|crores?|cr)\b"
    number = r"(\d+(?:\.\d+)?)"
    multiplier = {
        "lpa": 1.0,
        "lac": 1.0,
        "lacs": 1.0,
        "lakh": 1.0,
        "lakhs": 1.0,
        "cr": 100.0,
        "crore": 100.0,
        "crores": 100.0,
    }

    ranged = re.search(
        rf"{number}\s*(?:-|to)\s*{number}\s*{unit_pattern}", text
    )
    if ranged:
        return float(ranged.group(2)) * multiplier[ranged.group(3)]

    single = re.search(rf"{number}\s*{unit_pattern}", text)
    if single:
        return float(single.group(1)) * multiplier[single.group(2)]

    rupee_range = re.search(
        r"(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*"
        r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(?:per annum|p\.?a\.?|annual)",
        (salary_text or "").lower().replace(",", ""),
    )
    if rupee_range:
        return float(rupee_range.group(2)) / 100_000
    return None


def experience_includes_years(experience_text: str, years: int) -> bool:
    """Whether an explicit experience range includes the requested years."""
    text = (experience_text or "").lower()
    number = r"(\d+(?:\.\d+)?)"
    ranged = re.search(
        rf"{number}\s*(?:-|to)\s*{number}\s*(?:\+?\s*)?"
        r"(?:years?|yrs?)\b",
        text,
    )
    if ranged:
        return float(ranged.group(1)) <= years <= float(ranged.group(2))

    minimum = re.search(rf"{number}\s*\+\s*(?:years?|yrs?)\b", text)
    if minimum:
        return years >= float(minimum.group(1))

    single = re.search(rf"{number}\s*(?:years?|yrs?)\b", text)
    return bool(single and float(single.group(1)) == years)


@dataclass
class JobCard:
    job_id: str
    title: str
    company: str
    age_text: str
    required_skills: list[str]
    match_ratio: float = 0.0

    @property
    def age_hours(self) -> int:
        return age_to_hours(self.age_text)
