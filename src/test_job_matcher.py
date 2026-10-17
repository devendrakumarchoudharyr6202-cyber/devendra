"""Tests for job requirement parsing and matching."""

import unittest

from job_matcher import experience_overlaps_range


class ExperienceRangeTests(unittest.TestCase):
    def test_accepts_experience_range_within_or_overlapping_allowed_range(self):
        for experience in ("0-5 years", "1 to 3 yrs", "3-7 years", "5 years"):
            with self.subTest(experience=experience):
                self.assertTrue(experience_overlaps_range(experience, 0, 5))

    def test_accepts_fresher_and_plus_requirements_that_overlap(self):
        self.assertTrue(experience_overlaps_range("Fresher", 0, 5))
        self.assertTrue(experience_overlaps_range("5+ years", 0, 5))

    def test_rejects_experience_outside_allowed_range_or_unknown(self):
        for experience in ("6-8 years", "6+ years", "Experience not specified"):
            with self.subTest(experience=experience):
                self.assertFalse(experience_overlaps_range(experience, 0, 5))

    def test_rejects_invalid_allowed_range(self):
        with self.assertRaises(ValueError):
            experience_overlaps_range("1-3 years", 5, 0)


if __name__ == "__main__":
    unittest.main()
