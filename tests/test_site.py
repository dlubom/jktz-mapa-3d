import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.site import build, verify


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "dist"
        (self.output / "data").mkdir(parents=True)
        self.caves = self.root / "caves.json"
        self.caves.write_text(
            json.dumps(
                {
                    "crs": "EPSG:2180",
                    "origin": [566000, 153000, 0],
                    "source": {
                        "releaseId": 41,
                        "version": "v99.1",
                        "releaseUrl": "https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/tag/v99.1",
                        "modelSHA256": "a" * 64,
                        "assetId": 42,
                        "assetName": "JKTZ-v99.1.zip",
                        "assetSHA256": "b" * 64,
                    },
                    "counts": {"legs": 2, "stations": 3, "groups": 1},
                    "groups": [
                        {
                            "id": "NewCave",
                            "legs": [[1, 2, 3, 4, 5, 6], [4, 5, 6, 7, 8, 9]],
                        }
                    ],
                    "stations": [
                        {"position": [1, 2, 3]},
                        {"position": [4, 5, 6]},
                        {"position": [7, 8, 9]},
                    ],
                }
            )
        )
        self.inputs = self.root / "inputs.json"
        self.inputs.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "catalog": {
                        "release": {
                            "id": 41,
                            "tag": "v99.1",
                            "url": "https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/tag/v99.1",
                        },
                        "asset": {
                            "id": 42,
                            "name": "JKTZ-v99.1.zip",
                            "sha256": "b" * 64,
                        },
                    },
                }
            )
        )
        self.terrain = self.root / "terrain.json"
        for cloud in ["kozia", "regional"]:
            folder = self.output / "data" / cloud
            folder.mkdir()
            (folder / "metadata.json").write_text(
                json.dumps(
                    {
                        "scale": [0.001] * 3,
                        "offset": [1, 2, 3],
                        "boundingBox": {"min": [1, 2, 3]},
                    }
                )
            )
            (folder / "octree.bin").write_bytes(b"points")
            (folder / "hierarchy.bin").write_bytes(b"nodes")
        (self.output / "data/coverage-mask.bin.gz").write_bytes(b"mask")
        self.terrain.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "terrain_version": "test-v1",
                    "files": {
                        str(p.relative_to(self.output / "data")): {
                            "bytes": p.stat().st_size,
                            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        }
                        for p in (self.output / "data").rglob("*")
                        if p.is_file()
                    },
                }
            )
        )
        (self.output / "data/coverage.json").write_text(
            json.dumps(
                {
                    "coveredStations": 1,
                    "stationCount": 3,
                    "terrain_version": "test-v1",
                    "caves_sha256": hashlib.sha256(self.caves.read_bytes()).hexdigest(),
                }
            )
        )

    def test_dynamic_release_and_all_legs_with_relative_entrypoint(self):
        build(self.caves, self.inputs, self.terrain, self.output, "c" * 40)
        public = json.loads((self.output / "data/caves.json").read_text())
        self.assertEqual(public["counts"]["legs"], 2)
        self.assertEqual(public["groups"][0]["legs"][1], [4, 5, 6, 7, 8, 9])
        self.assertNotIn("stations", public)
        publication = json.loads((self.output / "publication.json").read_text())
        self.assertEqual(publication["catalog"]["version"], "v99.1")
        self.assertEqual(publication["commit"], "c" * 40)
        self.assertIn(
            "url=vendor/potree-next/jktz.html", (self.output / "index.html").read_text()
        )
        self.assertTrue(verify(self.output)["files"] > 100)

    def test_tampered_site_is_rejected(self):
        build(self.caves, self.inputs, self.terrain, self.output, "local")
        (self.output / "data/kozia/octree.bin").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify(self.output)

    def test_missing_cloud_stops_build(self):
        (self.output / "data/regional/octree.bin").unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")

    def test_unsupported_decoder_metadata_stops_build(self):
        p = self.output / "data/kozia/metadata.json"
        m = json.loads(p.read_text())
        m["scale"][1] = 0.01
        p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "decoder"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")

    def test_stale_catalog_inputs_stop_build_before_publishing_new_checksums(self):
        original = self.inputs.read_text()
        fields = [
            ("release", "id", 40),
            ("release", "tag", "v98.0"),
            ("release", "url", "https://example.invalid/old"),
            ("asset", "id", 1),
            ("asset", "name", "old.zip"),
            ("asset", "sha256", "0" * 64),
        ]
        for section, key, value in fields:
            with self.subTest(field=key):
                inputs = json.loads(original)
                inputs["catalog"][section][key] = value
                self.inputs.write_text(json.dumps(inputs))
                with self.assertRaisesRegex(ValueError, "catalog.*pin"):
                    build(self.caves, self.inputs, self.terrain, self.output, "local")
                self.assertFalse((self.output / "checksums.json").exists())

    def test_stale_coverage_for_changed_geometry_stops_build(self):
        model = json.loads(self.caves.read_text())
        model["groups"][0]["legs"][0][0] = 1.5
        model["stations"][0]["position"][0] = 1.5
        self.caves.write_text(json.dumps(model))
        with self.assertRaisesRegex(ValueError, "Coverage.*catalog"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")
        self.assertFalse((self.output / "publication.json").exists())
        self.assertFalse((self.output / "checksums.json").exists())

    def test_terrain_corrupted_between_fetch_and_build_cannot_get_new_checksums(self):
        for name in ["kozia/octree.bin", "coverage-mask.bin.gz"]:
            with self.subTest(file=name):
                path = self.output / "data" / name
                original = path.read_bytes()
                path.write_bytes(b"x" * len(original))
                try:
                    with self.assertRaisesRegex(ValueError, "SHA-256"):
                        build(
                            self.caves, self.inputs, self.terrain, self.output, "local"
                        )
                    self.assertFalse((self.output / "checksums.json").exists())
                finally:
                    path.write_bytes(original)

    def test_coverage_must_match_the_terrain_version_and_station_count(self):
        path = self.output / "data/coverage.json"
        original = json.loads(path.read_text())
        for key, value in [("terrain_version", "old-v0"), ("stationCount", 2)]:
            with self.subTest(field=key):
                coverage = dict(original, **{key: value})
                path.write_text(json.dumps(coverage))
                with self.assertRaisesRegex(ValueError, "Coverage"):
                    build(self.caves, self.inputs, self.terrain, self.output, "local")
                self.assertFalse((self.output / "checksums.json").exists())

    def test_terrain_manifest_cannot_omit_a_required_cloud_file(self):
        manifest = json.loads(self.terrain.read_text())
        del manifest["files"]["kozia/octree.bin"]
        self.terrain.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "terrain.*manifest"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")
        self.assertFalse((self.output / "checksums.json").exists())

    def test_terrain_manifest_paths_cannot_escape_the_data_directory(self):
        manifest = json.loads(self.terrain.read_text())
        manifest["files"]["../outside.bin"] = {
            "bytes": 7,
            "sha256": hashlib.sha256(b"outside").hexdigest(),
        }
        self.terrain.write_text(json.dumps(manifest))
        (self.output / "outside.bin").write_bytes(b"outside")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")
        self.assertFalse((self.output / "checksums.json").exists())

    def test_terrain_symlink_is_rejected_even_when_target_bytes_match(self):
        outside = self.root / "external.bin"
        outside.write_bytes(b"points")
        path = self.output / "data/kozia/octree.bin"
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            build(self.caves, self.inputs, self.terrain, self.output, "local")
        self.assertEqual(outside.read_bytes(), b"points")
        self.assertFalse((self.output / "checksums.json").exists())


if __name__ == "__main__":
    unittest.main()
