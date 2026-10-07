"""Unit tests for storage-state secret decoding (no browser needed)."""

import base64
import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from naukri_client import NaukriAgent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from set_session_secret import encode_storage_state  # noqa: E402


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
