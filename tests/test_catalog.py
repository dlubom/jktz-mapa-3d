"""Behavioral tests at the catalogue input/build boundaries."""

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import catalog

FIXTURE = Path(__file__).parent / "fixtures/survey.dump"


def release():
    return {
        "id": 123,
        "tag_name": "v3.2.1",
        "html_url": "https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/tag/v3.2.1",
        "published_at": "2026-11-16T16:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "id": 456,
                "name": "JKTZ-v3.2.1.zip",
                "size": 42,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": "https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/download/v3.2.1/JKTZ-v3.2.1.zip",
            },
            {"id": 999, "name": "documentation.zip"},
        ],
    }


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_resolve_pins_one_matching_release_asset_and_reuses_the_pin(self):
        output = self.root / "inputs.json"
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(release()).encode()),
        ):
            resolved = catalog.resolve_inputs(output)
        self.assertEqual(resolved["catalog"]["release"]["tag"], "v3.2.1")
        self.assertEqual(
            resolved["catalog"]["asset"],
            {
                "id": 456,
                "name": "JKTZ-v3.2.1.zip",
                "size": 42,
                "url": release()["assets"][0]["browser_download_url"],
                "sha256": "a" * 64,
            },
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("A pin must not query latest again"),
        ):
            self.assertEqual(catalog.resolve_inputs(output), resolved)

    def test_fetch_rejects_bad_checksum_without_caching_the_response(self):
        asset = {
            "name": "JKTZ-v3.2.1.zip",
            "url": release()["assets"][0]["browser_download_url"],
            "size": 4,
            "sha256": hashlib.sha256(b"good").hexdigest(),
        }
        cache = self.root / "cache"
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"evil")):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                catalog.fetch_asset(asset, cache)
        self.assertEqual(list(cache.iterdir()), [])

    def test_zip_accepts_identical_compiled_copies_but_not_distinct_models(self):
        archive = self.root / "release.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("exports/JKTZ-v3.2.1.3d", b"compiled model")
            package.writestr("KATASTER.3d", b"compiled model")
        self.assertEqual(
            catalog.read_model(archive), ("KATASTER.3d", b"compiled model")
        )
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("KATASTER.3d", b"compiled model")
            package.writestr("another.3d", b"different geometry")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            catalog.read_model(archive)

    def test_zip_rejects_unsafe_paths_even_outside_the_selected_model(self):
        archive = self.root / "unsafe.zip"
        for name in [
            "../escape.txt",
            "/absolute.txt",
            "C:/drive.txt",
            "dir\\escape.txt",
        ]:
            with self.subTest(name=name):
                with zipfile.ZipFile(archive, "w") as package:
                    package.writestr("KATASTER.3d", b"model")
                    package.writestr(name, b"unrelated")
                with self.assertRaisesRegex(ValueError, "Unsafe ZIP"):
                    catalog.read_model(archive)

    def test_geometry_keeps_every_station_leg_group_and_z_in_the_target_crs(self):
        result = catalog.geometry_from_dump(FIXTURE.read_text(), {"version": "v3.2.1"})
        self.assertEqual(result["crs"], "EPSG:2180")
        self.assertEqual(result["origin"], [566000, 153000, 0])
        self.assertEqual(
            result["counts"],
            {"stations": 3, "legs": 3, "groups": 3, "namedPrefixes": 2},
        )
        self.assertEqual(
            [s["name"] for s in result["stations"]], ["Alpha:0", "Alpha:section:1", ""]
        )
        # Independent literals from system GDAL 3.13.3, EPSG:32634 -> EPSG:2180.
        first = result["stations"][0]["position"]
        self.assertAlmostEqual(first[0], 565633.042055266, places=6)
        self.assertAlmostEqual(first[1], 152665.085677543, places=6)
        self.assertEqual(first[2], 1544.55)
        groups = {g["sourcePrefix"]: g for g in result["groups"]}
        self.assertEqual(set(groups), {"", "Alpha", "Beta"})
        self.assertEqual(groups[""]["legFlags"], ["SURFACE STYLE=NORMAL"])
        self.assertEqual(groups["Beta"]["legFlags"], ["DUPLICATE STYLE=NORMAL"])
        self.assertEqual(groups["Alpha"]["surveyLabels"], ["Alpha:survey"])
        for group in groups.values():
            self.assertEqual(group["legs"][0][:3], first)
            self.assertEqual(group["legs"][0][5], 1543.62)
        self.assertEqual(result["controls"], [])

    def test_geometry_rejects_truncated_or_unexpected_geometry_records(self):
        text = FIXTURE.read_text()
        for invalid in [
            text.removesuffix("STOP\n"),
            text.replace("STOP", "MOVE 1 2 3\nSTOP"),
        ]:
            with self.subTest(invalid=invalid[-40:]):
                with self.assertRaises(ValueError):
                    catalog.geometry_from_dump(invalid, {})

    def test_build_uses_the_pinned_archive_and_records_source_provenance(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as package:
            package.writestr("KATASTER.3d", b"small compiled fixture")
        payload = data.getvalue()
        metadata = release()
        metadata["assets"][0].update(
            size=len(payload), digest="sha256:" + hashlib.sha256(payload).hexdigest()
        )
        inputs, output = self.root / "inputs.json", self.root / "caves.json"
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(metadata).encode()),
        ):
            catalog.resolve_inputs(inputs)

        def dump_tool(command, **kwargs):
            self.assertEqual(command[0], "dump3d")
            if command[1] == "--version":
                return subprocess.CompletedProcess(
                    command, 0, "dump3d - Survex 1.4.4\n", ""
                )
            self.assertEqual(command[1], "--legs")
            self.assertEqual(Path(command[2]).read_bytes(), b"small compiled fixture")
            return subprocess.CompletedProcess(command, 0, FIXTURE.read_text(), "")

        with (
            patch("urllib.request.urlopen", return_value=io.BytesIO(payload)),
            patch("subprocess.run", side_effect=dump_tool),
        ):
            result = catalog.build_catalog(inputs, self.root / "cache", output)
        self.assertEqual(json.loads(output.read_text()), result)
        self.assertEqual(result["counts"]["legs"], 3)
        self.assertEqual(result["source"]["version"], "v3.2.1")
        self.assertEqual(result["source"]["releaseUrl"], metadata["html_url"])
        self.assertEqual(
            result["source"]["modelSHA256"],
            hashlib.sha256(b"small compiled fixture").hexdigest(),
        )
        self.assertIn("1.4.4", result["source"]["dump3dVersion"])

    def test_release_selection_rejects_unstable_missing_ambiguous_or_unhashed_assets(
        self,
    ):
        base = release()
        cases = []
        for flag in ["draft", "prerelease"]:
            value = copy.deepcopy(base)
            value[flag] = True
            cases.append(value)
        for assets in [
            [],
            [base["assets"][0], base["assets"][0]],
            [dict(base["assets"][0], digest=None)],
        ]:
            cases.append(dict(base, assets=assets))
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                output = self.root / f"rejected-{index}.json"
                with patch(
                    "urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps(value).encode()),
                ):
                    with self.assertRaises(ValueError):
                        catalog.resolve_inputs(output)
                self.assertFalse(output.exists())

    def test_invalid_existing_pin_is_not_replaced_by_a_new_latest_release(self):
        output = self.root / "inputs.json"
        output.write_text('{"schemaVersion":1,"catalog":{}}')
        original = output.read_bytes()
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Must not replace invalid input silently"),
        ):
            with self.assertRaises(ValueError):
                catalog.resolve_inputs(output)
        self.assertEqual(output.read_bytes(), original)

    def test_fetch_checks_size_and_validates_cached_bytes_without_network(self):
        asset = {
            "name": "JKTZ-v3.2.1.zip",
            "url": release()["assets"][0]["browser_download_url"],
            "size": 4,
            "sha256": hashlib.sha256(b"good").hexdigest(),
        }
        cache = self.root / "cache"
        for response in [b"bad", b"too long"]:
            with patch("urllib.request.urlopen", return_value=io.BytesIO(response)):
                with self.assertRaisesRegex(ValueError, "size"):
                    catalog.fetch_asset(asset, cache)
            self.assertEqual(list(cache.iterdir()), [])
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"good")):
            stored = catalog.fetch_asset(asset, cache)
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Valid cache is offline"),
        ):
            self.assertEqual(catalog.fetch_asset(asset, cache), stored)
            stored.write_bytes(b"evil")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                catalog.fetch_asset(asset, cache)

    def test_api_token_is_absent_from_asset_downloads_and_redirects(self):
        requests = []

        def response(request, **kwargs):
            requests.append(request)
            if request.full_url == catalog.API_URL:
                return io.BytesIO(json.dumps(release()).encode())
            return io.BytesIO(b"good")

        with (
            patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            patch("urllib.request.urlopen", side_effect=response),
        ):
            catalog.resolve_inputs(self.root / "inputs.json")
            catalog.fetch_asset(
                {
                    "name": "unused",
                    "url": release()["assets"][0]["browser_download_url"],
                    "size": 4,
                    "sha256": hashlib.sha256(b"good").hexdigest(),
                },
                self.root / "cache",
            )
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-token")
        self.assertIsNone(requests[1].get_header("Authorization"))
        redirect = urllib.request.HTTPRedirectHandler().redirect_request(
            requests[0],
            None,
            302,
            "Found",
            {},
            "https://release-assets.githubusercontent.com/blob",
        )
        self.assertIsNone(redirect.get_header("Authorization"))

    def test_geometry_rejects_wrong_crs_malformed_records_and_nonfinite_coordinates(
        self,
    ):
        text = FIXTURE.read_text()
        cases = [
            text.replace("EPSG:32634", "EPSG:3857"),
            text.replace("CS EPSG:32634\n", ""),
            text.replace("420067.00", "nan", 1),
            text.replace("NODE 420067.00", "NODE broken 420067.00", 1),
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid[:100]):
                with self.assertRaises(ValueError):
                    catalog.geometry_from_dump(invalid, {})


if __name__ == "__main__":
    unittest.main()
