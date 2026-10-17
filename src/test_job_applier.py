"""Tests for conservative job selection and application tracking."""

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_applier import _apply_on_detail, apply_jobs


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
                    experience_years=1,
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
                    experience_years=1,
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
                    experience_years=1,
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


if __name__ == "__main__":
    unittest.main()
