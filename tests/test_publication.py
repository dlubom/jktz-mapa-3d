import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.confirm_public import confirm


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = {
            "catalog": {
                "release": {
                    "tag": "v3",
                    "id": 3,
                    "url": "https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/tag/v3",
                },
                "asset": {"id": 4, "name": "JKTZ-v3.zip", "sha256": "a" * 64},
            }
        }
        source = {
            "version": "v3",
            "releaseId": 3,
            "releaseUrl": self.inputs["catalog"]["release"]["url"],
            "assetId": 4,
            "assetName": "JKTZ-v3.zip",
            "assetSHA256": "a" * 64,
        }
        self.publication = {
            "commit": "abc",
            "catalog": source.copy(),
            "counts": {"legs": 12},
            "terrain": {
                "files": {
                    "kozia/octree.bin": {"bytes": 100},
                    "regional/octree.bin": {"bytes": 100},
                }
            },
        }
        self.caves = {"source": source.copy(), "counts": {"legs": 12}}
        self.range_status = 206
        self.refresh()

    def refresh(self):
        self.data = json.dumps(self.caves).encode()
        self.model_sha = hashlib.sha256(self.data).hexdigest()
        self.publication_sha = hashlib.sha256(
            json.dumps(self.publication).encode()
        ).hexdigest()
        self.checksums = {"files": {"data/caves.json": {"sha256": self.model_sha}}}

    def read(self, url, headers=None):
        if "publication.json" in url:
            return 200, {}, json.dumps(self.publication).encode()
        if "inputs.json" in url:
            return 200, {}, json.dumps(self.inputs).encode()
        if "caves.json" in url:
            return 200, {}, self.data
        if "checksums.json" in url:
            return 200, {}, json.dumps(self.checksums).encode()
        return self.range_status, {"Content-Range": "bytes 0-31/100"}, bytes(32)

    def run_confirm(self, expected_inputs=None, **kwargs):
        return confirm(
            "https://example.org/map/",
            "abc",
            expected_inputs or self.inputs,
            self.model_sha,
            self.publication_sha,
            **kwargs,
        )

    def test_exact_inputs_commit_model_and_range(self):
        with patch("scripts.confirm_public.read", self.read):
            self.assertEqual(self.run_confirm(attempts=1)["status"], "PASS")

    def test_stale_inputs_rejected_even_if_commit_matches(self):
        expected = json.loads(json.dumps(self.inputs))
        expected["catalog"]["release"]["tag"] = "v2"
        with patch("scripts.confirm_public.read", self.read):
            with self.assertRaisesRegex(ValueError, "inputs"):
                self.run_confirm(expected, attempts=1)

    def test_range_full_response_rejected(self):
        self.range_status = 200
        with patch("scripts.confirm_public.read", self.read):
            with self.assertRaisesRegex(ValueError, "Range"):
                self.run_confirm(attempts=1)

    def test_same_commit_with_consistent_old_catalog_is_rejected(self):
        self.publication["catalog"]["version"] = "v2"
        self.caves["source"]["version"] = "v2"
        self.refresh()
        with patch("scripts.confirm_public.read", self.read):
            with self.assertRaisesRegex(ValueError, "pinned release"):
                self.run_confirm(attempts=1)

    def test_changed_publication_bytes_rejected(self):
        self.publication["builtAt"] = (
            "different deployment with same commit and release"
        )
        with patch("scripts.confirm_public.read", self.read):
            with self.assertRaisesRegex(ValueError, "publication checksum"):
                self.run_confirm(attempts=1)

    def test_retries_entire_snapshot_until_new_bytes_arrive(self):
        calls = 0

        def delayed(url, headers=None):
            nonlocal calls
            if "publication.json" in url:
                calls += 1
                if calls == 1:
                    return 200, {}, b"old publication"
            return self.read(url, headers)

        with (
            patch("scripts.confirm_public.read", delayed),
            patch("scripts.confirm_public.time.sleep"),
        ):
            self.assertEqual(self.run_confirm(attempts=2)["status"], "PASS")
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
