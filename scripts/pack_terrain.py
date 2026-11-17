"""Package the verified ALS 2025 and prepared NMT 2019 for a terrain release."""

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from terrain import load_manifest, sha256, tree_path, verify_file, verify_tree

RELEASE = "https://github.com/dlubom/jktz-mapa-3d/releases"
VERSION = "terrain-v2"


def file_record(path):
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def pack(base, base_manifest, nmt, sources, index, output):
    original = load_manifest(base_manifest)
    verify_tree(base, original["files"])
    verify_file(index, json.loads(sources.read_text())["index"])
    files = {
        name: tree_path(base, name)
        for name in original["files"]
        if name != "terrain-mask.json"
    }
    files["terrain-mask-als2025.json"] = base / "terrain-mask.json"
    for name in (
        "terrain-mask.json",
        "nmt2019-mask.bin.gz",
        "nmt2019-provenance.json",
        "nmt2019/metadata.json",
        "nmt2019/hierarchy.bin",
        "nmt2019/octree.bin",
    ):
        files[name] = nmt / name
    files["provenance/nmt2019-index.gml"] = index
    files["provenance/nmt2019-sources.json"] = sources
    metadata = json.loads(files["nmt2019/metadata.json"].read_text())
    clouds = {
        **original["clouds"],
        "nmt2019": {
            "metadata": "nmt2019/metadata.json",
            "points": metadata["points"],
            "source": "GUGiK photogrammetric NMT 2019, native 5 m",
        },
    }
    write_bundle(output, VERSION, files, clouds)


def write_bundle(output, version, files, clouds):
    checksums = {name: file_record(path) for name, path in files.items()}
    output.mkdir(parents=True, exist_ok=False)
    archive_path = output / f"{version}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, path in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(entry, "w") as target:
                shutil.copyfileobj(source, target)
    manifest = {
        "schema_version": 1,
        "terrain_version": version,
        "archive": {
            "name": archive_path.name,
            "url": f"{RELEASE}/download/{version}/{archive_path.name}",
            **file_record(archive_path),
        },
        "clouds": clouds,
        "files": checksums,
        "release": {"tag": version, "url": f"{RELEASE}/tag/{version}"},
    }
    (output / "terrain.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "base-manifest", "nmt", "sources", "index", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    pack(args.base, args.base_manifest, args.nmt, args.sources, args.index, args.output)
