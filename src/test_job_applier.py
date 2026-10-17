"""Tests for conservative job selection and application tracking."""

import csv
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from job_applier import (
    IST,
    _apply_on_detail,
    _count_daily_applications,
    apply_jobs,
)


class _Locator:
    def __init__(self, text="", visible=False):
        self.text = text
        self.visible = visible
        self.clicks = 0

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.visible or self.text else 0

    def inner_text(self):
        return self.text

    def click(self, **kwargs):
        self.clicks += 1

    def is_visible(self):
        return self.visible

    def nth(self, index):
        return self


class _ConfirmationPage:
    def __init__(self):
        self.apply_button = _Locator("Apply", visible=True)
        self.submit_button = _Locator("Submit", visible=True)

    def goto(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, *args):
        pass

    def locator(self, selector):
        if selector == "body":
            return _Locator("Please confirm your application", visible=True)
        if selector.startswith("#apply-button,"):
            return self.apply_button
        return _Locator()

    def get_by_role(self, role, *, name):
        return self.submit_button


class JobApplicationTests(unittest.TestCase):
    def _job(self):
        return {
            "job_id": "1234567890",
            "title": "Junior Data Analyst",
            "company": "Example Analytics",
            "href": "https://www.naukri.com/job-listings-1234567890",
            "age_text": "2 hours ago",
            "experience_text": "0-1 years",
            "required_skills": ["Python", "SQL"],
            "already_applied": False,
        }

    def test_final_confirmation_is_not_clicked(self):
        page = _ConfirmationPage()

        success, status = _apply_on_detail(
            page, "https://example.test/job", dry_run=False
        )

        self.assertFalse(success)
        self.assertIn("Awaiting user approval", status)
        self.assertEqual(page.apply_button.clicks, 1)
        self.assertEqual(page.submit_button.clicks, 0)

    def test_pending_application_is_recorded_and_not_retried(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "applications.csv"
            env = patch.dict(os.environ, {"NAUKRI_APPLICATION_LOG_PATH": str(log_path)})
            with (
                env,
                patch("job_applier.collect_recommended_jobs", return_value=[self._job()]),
                patch("job_applier.collect_search_jobs", return_value=[]),
                patch(
                    "job_applier._apply_on_detail",
                    return_value=(
                        False,
                        "Awaiting user approval: final submission was not clicked",
                    ),
                ) as apply_detail,
            ):
                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    search_queries=["Junior Data Analyst"],
                    experience_min_years=0,
                    experience_max_years=5,
                    target_titles=["Data Analyst", "Junior Data Analyst"],
                )

                self.assertEqual(result["jobs_matching_criteria"], 1)
                self.assertEqual(len(result["applications_unconfirmed"]), 1)
                self.assertEqual(
                    result["applications_unconfirmed"][0]["status"],
                    "pending_confirmation",
                )
                with log_path.open(encoding="utf-8", newline="") as csv_file:
                    rows = list(csv.DictReader(csv_file))
                self.assertEqual(rows[0]["company"], "Example Analytics")
                self.assertEqual(rows[0]["title"], "Junior Data Analyst")
                self.assertEqual(rows[0]["application_link"], self._job()["href"])
                self.assertEqual(rows[0]["status"], "pending_confirmation")
                self.assertTrue(rows[0]["date_ist"].endswith("+05:30"))

                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    search_queries=["Junior Data Analyst"],
                    experience_min_years=0,
                    experience_max_years=5,
                    target_titles=["Data Analyst", "Junior Data Analyst"],
                )

            self.assertEqual(result["jobs_matching_criteria"], 0)
            self.assertIn(
                "Application already recorded as pending_confirmation",
                [row["reason"] for row in result["skipped"]],
            )
            apply_detail.assert_called_once()

    def test_missing_apply_button_is_skipped_and_next_job_is_tried(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "applications.csv"
            first_job = self._job()
            second_job = {
                **self._job(),
                "job_id": "0987654321",
                "title": "Data Analyst",
                "company": "Next Analytics",
                "href": "https://www.naukri.com/job-listings-0987654321",
            }
            env = patch.dict(os.environ, {"NAUKRI_APPLICATION_LOG_PATH": str(log_path)})
            with (
                env,
                patch(
                    "job_applier.collect_recommended_jobs",
                    return_value=[first_job, second_job],
                ),
                patch("job_applier.collect_search_jobs", return_value=[]),
                patch(
                    "job_applier._apply_on_detail",
                    side_effect=[
                        (False, "Apply button unavailable"),
                        (True, "Application confirmation shown"),
                    ],
                ) as apply_detail,
            ):
                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    max_apply=1,
                    search_queries=["Junior Data Analyst"],
                    experience_min_years=0,
                    experience_max_years=5,
                    target_titles=["Data Analyst", "Junior Data Analyst"],
                )

            self.assertEqual(apply_detail.call_count, 2)
            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(
                result["applications_submitted"][0]["company"], "Next Analytics"
            )
            self.assertEqual(result["skipped"][0]["status"], "apply_unavailable")
            with log_path.open(encoding="utf-8", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(
                [(row["job_id"], row["status"]) for row in rows],
                [("1234567890", "apply_unavailable"), ("0987654321", "submitted")],
            )

    def test_only_jobs_with_experience_overlapping_configured_range_are_eligible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs = [
                {**self._job(), "job_id": "1", "experience_text": "0-5 years"},
                {**self._job(), "job_id": "2", "experience_text": "3-7 years"},
                {**self._job(), "job_id": "3", "experience_text": "6+ years"},
            ]
            env = patch.dict(
                os.environ,
                {"NAUKRI_APPLICATION_LOG_PATH": str(Path(temp_dir) / "applications.csv")},
            )
            with (
                env,
                patch("job_applier.collect_recommended_jobs", return_value=jobs),
                patch("job_applier.collect_search_jobs", return_value=[]),
                patch("job_applier._apply_on_detail", return_value=(False, "Already applied")),
            ):
                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    max_apply=1,
                    experience_min_years=0,
                    experience_max_years=5,
                    search_queries=[],
                    target_titles=["Data Analyst"],
                )

            self.assertEqual(
                [job["job_id"] for job in result["selected"]], ["1", "2"]
            )
            self.assertIn(
                "Experience requirement does not clearly include the 0–5-year range",
                [row["reason"] for row in result["skipped"]],
            )

    def test_can_skip_title_and_skill_filters_when_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            unrelated_job = {
                **self._job(),
                "title": "Office Assistant",
                "required_skills": ["Unrelated Skill"],
            }
            env = patch.dict(
                os.environ,
                {"NAUKRI_APPLICATION_LOG_PATH": str(Path(temp_dir) / "applications.csv")},
            )
            with (
                env,
                patch(
                    "job_applier.collect_recommended_jobs",
                    return_value=[unrelated_job],
                ),
                patch("job_applier.collect_search_jobs", return_value=[]),
                patch(
                    "job_applier._apply_on_detail",
                    return_value=(False, "Apply button unavailable"),
                ),
            ):
                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    min_match=0.60,
                    require_skill_match=False,
                    require_target_title_match=False,
                    experience_min_years=0,
                    experience_max_years=5,
                    search_queries=[],
                )

            self.assertEqual(result["jobs_matching_criteria"], 1)
            self.assertEqual(result["selected"][0]["title"], "Office Assistant")
            self.assertEqual(result["selected"][0]["match"], 0.0)
            self.assertNotIn(
                "Title does not match a configured target role",
                [row["reason"] for row in result["skipped"]],
            )
            self.assertNotIn(
                "Skill match below 60%",
                [row["reason"] for row in result["skipped"]],
            )

    def test_daily_application_count_uses_submitted_and_unconfirmed_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "applications.csv"
            yesterday_ist = (
                (datetime.now(IST).date() - timedelta(days=1)).isoformat()
                + "T23:59:00+05:30"
            )
            today_ist = datetime.now(IST).isoformat(timespec="seconds")
            with log_path.open("w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=[
                        "date_ist",
                        "job_id",
                        "company",
                        "title",
                        "application_link",
                        "status",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"date_ist": today_ist, "job_id": "1", "status": "submitted"},
                        {"date_ist": today_ist, "job_id": "2", "status": "submission_unconfirmed"},
                        {"date_ist": today_ist, "job_id": "3", "status": "pending_confirmation"},
                        {"date_ist": yesterday_ist, "job_id": "4", "status": "submitted"},
                    ]
                )

            self.assertEqual(
                _count_daily_applications(log_path, datetime.now(IST).date()), 2
            )

    def test_daily_limit_exhaustion_prevents_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "applications.csv"
            env = patch.dict(os.environ, {"NAUKRI_APPLICATION_LOG_PATH": str(log_path)})
            with (
                env,
                patch("job_applier.collect_recommended_jobs", return_value=[self._job()]),
                patch("job_applier.collect_search_jobs", return_value=[]),
                patch("job_applier._count_daily_applications", return_value=50),
                patch("job_applier._apply_on_detail") as apply_detail,
            ):
                result = apply_jobs(
                    object(),
                    ["Python", "SQL"],
                    max_apply=50,
                    daily_limit=50,
                    search_queries=["Junior Data Analyst"],
                    experience_min_years=0,
                    experience_max_years=5,
                    target_titles=["Data Analyst", "Junior Data Analyst"],
                )

            self.assertEqual(result["daily_application_count"], 50)
            self.assertEqual(result["daily_application_slots_remaining"], 0)
            self.assertIn("daily application limit", result["message"])
            apply_detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
