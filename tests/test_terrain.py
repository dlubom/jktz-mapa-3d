"""Terrain fetch integrity and native-cell coverage contracts, without network/GDAL."""

import gzip
import hashlib
import io
import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import terrain


def record(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


class TerrainFetchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.files = {
            "kozia/metadata.json": b'{"points":1}',
            "kozia/octree.bin": b"abcd",
        }
        self.archive = zip_bytes(self.files)
        self.manifest = {
            "schema_version": 1,
            "terrain_version": "test-v1",
            "archive": {
                "url": "https://example.invalid/terrain.zip",
                **record(self.archive),
            },
            "files": {name: record(data) for name, data in self.files.items()},
        }
        self.path = self.root / "terrain.json"
        save_json(self.path, self.manifest)

    def fetch(self, archive=None):
        with patch.object(
            terrain,
            "urlopen",
            return_value=io.BytesIO(self.archive if archive is None else archive),
        ):
            return terrain.fetch(self.path, self.root / "cache", self.root / "output")

    def test_fetch_verifies_each_file_and_reuses_verified_cache(self):
        self.fetch()
        self.assertEqual((self.root / "output/kozia/octree.bin").read_bytes(), b"abcd")
        with patch.object(
            terrain, "urlopen", side_effect=AssertionError("Unexpected network")
        ):
            result = terrain.fetch(self.path, self.root / "cache", self.root / "output")
        self.assertTrue(result["cache_hit"])

    def test_wrong_archive_checksum_does_not_publish(self):
        self.manifest["archive"]["sha256"] = "0" * 64
        save_json(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.fetch()
        self.assertFalse((self.root / "cache").exists())
        self.assertFalse((self.root / "output").exists())

    def test_archive_larger_than_pinned_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds pinned"):
            self.fetch(self.archive + b"unexpected")

    def test_wrong_inner_checksum_does_not_publish(self):
        self.manifest["files"]["kozia/octree.bin"]["sha256"] = "0" * 64
        save_json(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.fetch()
        self.assertFalse((self.root / "cache").exists())

    def test_tampered_cache_is_repaired_and_unrelated_output_preserved(self):
        self.fetch()
        (self.root / "cache/kozia/octree.bin").write_bytes(b"evil")
        (self.root / "output/caves.json").write_text("caves")
        result = self.fetch()
        self.assertFalse(result["cache_hit"])
        self.assertEqual((self.root / "cache/kozia/octree.bin").read_bytes(), b"abcd")
        self.assertEqual((self.root / "output/caves.json").read_text(), "caves")

    def test_symlink_output_is_not_followed(self):
        self.fetch()
        target = self.root / "output/kozia/octree.bin"
        target.unlink()
        outside = self.root / "unrelated.bin"
        outside.write_bytes(b"preserve")
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.fetch()
        self.assertEqual(outside.read_bytes(), b"preserve")

    def test_unsafe_names_are_rejected_before_writing(self):
        for name in [
            "../outside",
            "/absolute",
            "a/../outside",
            "a\\outside",
            "C:/outside",
            "./a",
            "a//b",
        ]:
            with self.subTest(name=name):
                archive = self.root / "unsafe.zip"
                archive.write_bytes(zip_bytes({name: b"evil"}))
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    terrain.extract_verified(
                        archive, self.root / "unsafe-output", {name: record(b"evil")}
                    )
                self.assertFalse((self.root / "unsafe-output").exists())

    def test_zip_symlink_is_rejected_before_writing(self):
        archive = self.root / "symlink.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, b"../outside")
        with self.assertRaisesRegex(ValueError, "Unsupported archive entry"):
            terrain.extract_verified(
                archive, self.root / "unsafe-output", {"link": record(b"../outside")}
            )
        self.assertFalse((self.root / "unsafe-output").exists())

    def test_duplicate_entries_are_rejected_before_writing(self):
        archive = self.root / "duplicate.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("file", b"a")
                bundle.writestr("file", b"a")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            terrain.extract_verified(
                archive, self.root / "unsafe-output", {"file": record(b"a")}
            )
        self.assertFalse((self.root / "unsafe-output").exists())

    def test_extra_archive_files_are_rejected(self):
        archive = self.root / "extra.zip"
        archive.write_bytes(zip_bytes({"file": b"a", "extra": b"b"}))
        with self.assertRaisesRegex(ValueError, "Unexpected archive"):
            terrain.extract_verified(
                archive, self.root / "unsafe-output", {"file": record(b"a")}
            )


class NativeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        # Northern row: valid, NoData, valid. Southern row: NoData, valid, NoData.
        bits = bytes([0b10101000])
        compressed = gzip.compress(bits, mtime=0)
        (self.root / "coverage-mask.bin.gz").write_bytes(compressed)
        self.metadata = {
            "schema_version": 1,
            "terrain_version": "test-v1",
            "encoding": "row-major-msb-first-bitpack-gzip",
            "file": "coverage-mask.bin.gz",
            "width": 3,
            "height": 2,
            "geotransform": [10, 1, 0, 20, 0, -1],
            "crs": "EPSG:2180",
            "vertical_datum": "PL-EVRF2007-NH",
            "valid_cells": 3,
            "compressed": record(compressed),
            "uncompressed_sha256": hashlib.sha256(bits).hexdigest(),
        }
        save_json(self.root / "terrain-mask.json", self.metadata)

    def test_native_nodata_and_half_open_outer_bounds(self):
        metadata, bits = terrain.load_mask(self.root)
        expected = [
            (10, 20, True),
            (10.5, 19.5, True),
            (11, 19.5, False),
            (12, 19.5, True),
            (11.5, 18.5, True),
            (12.5, 18.5, False),
            (13, 19, False),
            (10, 18, False),
            (9.999, 19.5, False),
            (10.5, 20.001, False),
        ]
        for x, y, good in expected:
            with self.subTest(x=x, y=y):
                self.assertEqual(terrain.covered(metadata, bits, x, y), good)

    def test_counts_actual_station_records_and_updates_percentage(self):
        caves = {
            "crs": "EPSG:2180",
            "stations": [
                {"name": "A:1", "position": [10.5, 19.5, 0]},
                {"name": "A:duplicate", "position": [10.5, 19.5, 100]},
                {"name": "A:2", "position": [11.5, 19.5, 500]},
                {"name": "B:1", "position": [11.5, 18.5, 1000]},
                {"name": "C:1", "position": [99, 99, 999]},
            ],
        }
        source = self.root / "caves.json"
        save_json(source, caves)
        result = terrain.coverage(self.root, source, self.root / "coverage.json")
        self.assertEqual(result["stationCount"], 5)
        self.assertEqual(result["coveredStations"], 3)
        self.assertEqual(result["percent"], 60)
        self.assertEqual(
            result["groups"], {"total": 3, "full": 1, "partial": 1, "none": 1}
        )
        self.assertIn("3 z 5 stacji (60,0%)", result["description"])
        caves["stations"].append({"name": "D:1", "position": [100, 100, 100]})
        save_json(source, caves)
        self.assertEqual(
            terrain.coverage(self.root, source, self.root / "coverage.json")["percent"],
            50,
        )

    def test_mask_checksum_and_dimensions_are_checked(self):
        (self.root / "coverage-mask.bin.gz").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            terrain.load_mask(self.root)

    def test_expanded_model_reports_gain_and_loss_against_als(self):
        old_metadata = dict(self.metadata)
        save_json(self.root / "terrain-mask-als2025.json", old_metadata)
        bits = bytes([0b01110000])
        compressed = gzip.compress(bits, mtime=0)
        (self.root / "nmt2019-mask.bin.gz").write_bytes(compressed)
        save_json(
            self.root / "terrain-mask.json",
            dict(
                self.metadata,
                terrain_version="test-v2",
                source="NMT 2019",
                comparison_mask="terrain-mask-als2025.json",
                file="nmt2019-mask.bin.gz",
                compressed=record(compressed),
                uncompressed_sha256=hashlib.sha256(bits).hexdigest(),
            ),
        )
        source = self.root / "caves.json"
        save_json(
            source,
            {
                "crs": "EPSG:2180",
                "stations": [
                    {"name": f"A:{i}", "position": [x, y, 0]}
                    for i, (x, y) in enumerate(
                        [(10.5, 19.5), (11.5, 19.5), (12.5, 19.5), (10.5, 18.5)]
                    )
                ],
            },
        )
        result = terrain.coverage(self.root, source, self.root / "coverage.json")
        self.assertEqual(result["coveredStations"], 3)
        self.assertEqual(result["als2025"]["coveredStations"], 2)
        self.assertEqual(result["als2025"]["additionalStations"], 2)
        self.assertEqual(result["als2025"]["onlyAls2025Stations"], 1)
        self.assertIn("NMT 2019", result["description"])

    def test_wrong_crs_and_nonfinite_station_fail(self):
        source = self.root / "caves.json"
        save_json(source, {"crs": "EPSG:32634", "stations": []})
        with self.assertRaisesRegex(ValueError, "EPSG:2180"):
            terrain.coverage(self.root, source, self.root / "coverage.json")
        save_json(
            source,
            {
                "crs": "EPSG:2180",
                "stations": [{"name": "A:1", "position": [float("nan"), 19, 0]}],
            },
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            terrain.coverage(self.root, source, self.root / "coverage.json")

    def test_dmr_supplement_only_adds_stations_in_nmt_gaps(self):
        save_json(
            self.root / "terrain-mask.json",
            dict(self.metadata, supplement_mask="dmr5-mask.json"),
        )
        bits = bytes([0b11010000])
        compressed = gzip.compress(bits, mtime=0)
        (self.root / "dmr5-mask.bin.gz").write_bytes(compressed)
        save_json(
            self.root / "dmr5-mask.json",
            dict(
                self.metadata,
                file="dmr5-mask.bin.gz",
                compressed=record(compressed),
                uncompressed_sha256=hashlib.sha256(bits).hexdigest(),
            ),
        )
        source = self.root / "caves.json"
        save_json(
            source,
            {
                "crs": "EPSG:2180",
                "stations": [
                    {"name": "PL:overlap", "position": [10.5, 19.5, 0]},
                    {"name": "SK:only", "position": [11.5, 19.5, 0]},
                    {"name": "PL:only", "position": [12.5, 19.5, 0]},
                    {"name": "Other:missing", "position": [12.5, 18.5, 0]},
                ],
            },
        )
        result = terrain.coverage(self.root, source, self.root / "coverage.json")
        self.assertEqual(result["coveredStations"], 3)
        self.assertEqual(result["by_group"]["SK"]["covered"], 1)
        self.assertEqual(result["dmr5"]["additionalStations"], 1)
        self.assertEqual(result["dmr5"]["nmt2019Stations"], 2)


if __name__ == "__main__":
    unittest.main()
