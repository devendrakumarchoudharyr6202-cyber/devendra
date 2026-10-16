"""Unit tests for storage-state secret decoding (no browser needed)."""

import base64
import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from naukri_client import NaukriAgent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from set_session_secret import (  # noqa: E402
    encode_storage_state,
    find_github_cli,
    repository_from_origin,
)


class GitHubCliTests(unittest.TestCase):
    def test_finds_installed_cli_outside_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "GitHub CLI" / "gh.exe"
            executable.parent.mkdir()
            executable.touch()

            with (
                patch("set_session_secret.shutil.which", return_value=None),
                patch.dict(os.environ, {"ProgramFiles": temp_dir}),
            ):
                self.assertEqual(find_github_cli(), str(executable))


class SessionSecretRepositoryTests(unittest.TestCase):
    def test_repository_from_https_origin(self):
        self.assertEqual(
            repository_from_origin(
                "https://github.com/devendrakumarchoudharyr6202-cyber/"
                "devendra.git"
            ),
            "devendrakumarchoudharyr6202-cyber/devendra",
        )

    def test_repository_from_ssh_origin(self):
        self.assertEqual(
            repository_from_origin(
                "git@github.com:devendrakumarchoudharyr6202-cyber/devendra.git"
            ),
            "devendrakumarchoudharyr6202-cyber/devendra",
        )

    def test_rejects_non_github_origin(self):
        with self.assertRaisesRegex(SystemExit, "GitHub repository"):
            repository_from_origin("https://example.com/owner/repo.git")


class StorageStateSecretTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.artifacts = self.temp_root / "artifacts"
        self.artifacts.mkdir()
        self.agent = object.__new__(NaukriAgent)
        self.state = {
            "cookies": [{"name": "session", "value": "private"}],
            "origins": [],
        }
        self.env = patch.dict(os.environ, clear=False)
        self.env.start()
        os.environ.pop("NAUKRI_STORAGE_STATE_GZ_B64", None)
        os.environ.pop("NAUKRI_STORAGE_STATE_B64", None)
        self.artifacts_patch = patch("naukri_client.ARTIFACTS", self.artifacts)
        self.artifacts_patch.start()
        self.tempfile_patch = patch(
            "naukri_client.tempfile.tempdir", str(self.temp_root)
        )
        self.tempfile_patch.start()

    def tearDown(self):
        self.tempfile_patch.stop()
        self.artifacts_patch.stop()
        self.env.stop()
        self.temp_dir.cleanup()

    def test_load_storage_state_from_compressed_secret(self):
        compressed = gzip.compress(json.dumps(self.state).encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("ascii")
        os.environ["NAUKRI_STORAGE_STATE_GZ_B64"] = encoded
        os.environ["NAUKRI_STORAGE_STATE_B64"] = "deliberately-invalid"

        result = self.agent._load_storage_state()

        self.assertIsNotNone(result)
        self.assertNotEqual(Path(result).parent, self.artifacts)
        self.assertEqual(
            json.loads(Path(result).read_text(encoding="utf-8")),
            self.state,
        )

    def test_compressed_secret_builder_removes_only_large_recommendation_cache(self):
        path = self.artifacts / "storage_state.json"
        cache_name = "srp_simjobs_reco_wdgt_example"
        source = {
            "cookies": self.state["cookies"],
            "origins": [
                {
                    "origin": "https://www.naukri.com",
                    "localStorage": [
                        {"name": cache_name, "value": "large cache"},
                        {"name": "auth-token", "value": "keep"},
                    ],
                }
            ],
        }
        path.write_text(json.dumps(source), encoding="utf-8")

        encoded, compact_size = encode_storage_state(path)
        decoded = json.loads(gzip.decompress(base64.b64decode(encoded)))

        self.assertLess(len(encoded), 48 * 1024)
        self.assertLess(compact_size, path.stat().st_size)
        self.assertEqual(
            decoded["origins"][0]["localStorage"],
            [{"name": "auth-token", "value": "keep"}],
        )

    def test_load_storage_state_from_legacy_base64_secret(self):
        os.environ["NAUKRI_STORAGE_STATE_B64"] = base64.b64encode(
            json.dumps(self.state).encode("utf-8")
        ).decode("ascii")

        result = self.agent._load_storage_state()

        self.assertIsNotNone(result)
        self.assertNotEqual(Path(result).parent, self.artifacts)
        self.assertEqual(
            json.loads(Path(result).read_text(encoding="utf-8")),
            self.state,
        )

    def test_invalid_compressed_secret_has_actionable_error(self):
        os.environ["NAUKRI_STORAGE_STATE_GZ_B64"] = "not-encoded"

        with self.assertRaisesRegex(
            RuntimeError, "NAUKRI_STORAGE_STATE_GZ_B64"
        ):
            self.agent._load_storage_state()


class ResumeSummaryRunTests(unittest.TestCase):
    def test_browser_launch_disables_http2(self):
        agent = object.__new__(NaukriAgent)
        agent.headless = True
        agent.timeout = 1000
        browser = MagicMock()
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser

        with patch.object(agent, "_load_storage_state", return_value=None):
            agent._launch(playwright)

        launch_kwargs = playwright.chromium.launch.call_args.kwargs
        self.assertIn("--disable-http2", launch_kwargs["args"])

    def test_login_checks_profile_directly_for_existing_session(self):
        agent = object.__new__(NaukriAgent)
        agent.email = ""
        agent.password = ""
        page = MagicMock()

        with (
            patch.object(agent, "_assert_not_blocked"),
            patch.object(agent, "_dismiss_overlays"),
            patch.object(agent, "_is_logged_in", return_value=True),
        ):
            agent._login(page)

        page.goto.assert_called_once_with(
            "https://www.naukri.com/mnjuser/profile",
            wait_until="commit",
            timeout=90000,
        )

    def test_resume_run_only_updates_summary_and_uploads_resume(self):
        agent = object.__new__(NaukriAgent)
        agent.dry_run = False
        agent.cfg = {
            "scheduled_summary": (
                "Full Stack Developer with 6+ years of experience."
            )
        }
        browser = MagicMock()
        page = MagicMock()
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = object()

        with (
            patch("naukri_client.sync_playwright", return_value=playwright_context),
            patch.object(agent, "_launch", return_value=(browser, page)),
            patch.object(agent, "_assert_not_blocked"),
            patch.object(agent, "_login"),
            patch.object(agent, "_reupload_resume", return_value=True) as upload,
            patch.object(agent, "_save_storage"),
            patch.object(agent, "_screenshot"),
            patch.object(agent, "_update_headline") as headline,
            patch.object(
                agent, "_update_summary", side_effect=[True, True]
            ) as summary,
            patch.object(agent, "_update_skills") as skills,
        ):
            result = agent.run_resume_summary()

        self.assertEqual(
            result,
            {
                "summary_updated": True,
                "resume_uploaded": True,
                "dry_run": False,
            },
        )
        self.assertEqual(
            summary.call_args_list,
            [
                unittest.mock.call(
                    page,
                    "with 6+ years of experience.",
                    ensure_absent="Full Stack Developer",
                ),
                unittest.mock.call(
                    page, agent.cfg["scheduled_summary"]
                ),
            ],
        )
        upload.assert_called_once_with(page)
        headline.assert_not_called()
        skills.assert_not_called()
        browser.close.assert_called_once()

    def test_summary_remove_step_fails_if_phrase_remains_visible(self):
        agent = object.__new__(NaukriAgent)
        agent.dry_run = False
        page = MagicMock()
        page.locator.return_value.count.return_value = 1
        page.evaluate.return_value = (
            "Full Stack Developer with 6+ years of experience."
        )

        with (
            patch.object(agent, "_open_widget_editor", return_value=True),
            patch.object(agent, "_click_save", return_value=True),
            patch.object(agent, "_screenshot"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "could not be verified"
            ):
                agent._update_summary(
                    page,
                    "with 6+ years of experience.",
                    ensure_absent="Full Stack Developer",
                )

    def test_resume_run_retries_if_adding_summary_opening_fails(self):
        agent = object.__new__(NaukriAgent)
        agent.dry_run = False
        agent.cfg = {
            "scheduled_summary": (
                "Full Stack Developer with 6+ years of experience."
            )
        }
        browser = MagicMock()
        page = MagicMock()
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = object()

        with (
            patch("naukri_client.sync_playwright", return_value=playwright_context),
            patch.object(agent, "_launch", return_value=(browser, page)),
            patch.object(agent, "_assert_not_blocked"),
            patch.object(agent, "_login"),
            patch.object(agent, "_reupload_resume", return_value=True),
            patch.object(agent, "_save_storage"),
            patch.object(agent, "_screenshot"),
            patch.object(
                agent,
                "_update_summary",
                side_effect=[True, RuntimeError("temporary save issue"), True],
            ) as summary,
        ):
            result = agent.run_resume_summary()

        self.assertTrue(result["summary_updated"])
        self.assertEqual(summary.call_count, 3)
        self.assertEqual(
            summary.call_args_list[-1],
            unittest.mock.call(page, agent.cfg["scheduled_summary"]),
        )

    def test_resume_download_verification_rejects_different_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "resume.pdf"
            downloaded = Path(temp_dir) / "downloaded.pdf"
            source.write_bytes(b"%PDF-1.7\nsource\n%%EOF")
            downloaded.write_bytes(b"%PDF-1.7\nother resume\n%%EOF")

            with self.assertRaisesRegex(
                RuntimeError, "does not match the configured PDF"
            ):
                NaukriAgent._verify_resume_download(source, downloaded)

    def test_resume_download_verification_rejects_invalid_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "resume.pdf"
            downloaded = Path(temp_dir) / "downloaded.pdf"
            source.write_bytes(b"%PDF-1.7\nsource\n%%EOF")
            downloaded.write_bytes(b"")

            with self.assertRaisesRegex(RuntimeError, "not a complete PDF"):
                NaukriAgent._verify_resume_download(source, downloaded)

    def test_resume_download_verification_accepts_exact_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "resume.pdf"
            downloaded = Path(temp_dir) / "downloaded.pdf"
            source.write_bytes(b"%PDF-1.7\nsource\n%%EOF")
            downloaded.write_bytes(source.read_bytes())

            NaukriAgent._verify_resume_download(source, downloaded)
