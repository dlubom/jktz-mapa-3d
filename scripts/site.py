"""Assemble and verify the static site from already verified data inputs."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .terrain import check_record, verify_tree
else:
    from terrain import check_record, verify_tree

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def build(caves_path, inputs_path, terrain_path, output, commit):
    model = json.loads(Path(caves_path).read_text())
    inputs = json.loads(Path(inputs_path).read_text())
    terrain = json.loads(Path(terrain_path).read_text())
    output = Path(output)
    if model["crs"] != "EPSG:2180" or model["origin"] != [566000, 153000, 0]:
        raise ValueError("Unexpected scene reference system")
    if (
        not model["groups"]
        or sum(len(g["legs"]) for g in model["groups"]) != model["counts"]["legs"]
    ):
        raise ValueError("Incomplete cave geometry")
    for cloud in ["kozia", "regional"]:
        for name in ["metadata.json", "hierarchy.bin", "octree.bin"]:
            if not (output / "data" / cloud / name).is_file():
                raise ValueError(f"Missing terrain {cloud}/{name}")
        metadata = json.loads((output / "data" / cloud / "metadata.json").read_text())
        if (
            len(set(metadata["scale"])) != 1
            or metadata["offset"] != metadata["boundingBox"]["min"]
        ):
            raise ValueError(
                "Unsupported coordinate metadata for pinned Potree decoder"
            )
    coverage = json.loads((output / "data/coverage.json").read_text())
    try:
        release, asset = inputs["catalog"]["release"], inputs["catalog"]["asset"]
        expected_source = {
            "releaseId": release["id"],
            "version": release["tag"],
            "releaseUrl": release["url"],
            "assetId": asset["id"],
            "assetName": asset["name"],
            "assetSHA256": asset["sha256"],
        }
        actual_source = {key: model["source"][key] for key in expected_source}
    except (KeyError, TypeError):
        raise ValueError("Incomplete catalog pin provenance") from None
    if actual_source != expected_source:
        raise ValueError("Model catalog source differs from the input pin")
    if coverage.get("caves_sha256") != digest(Path(caves_path)):
        raise ValueError("Coverage does not match the catalog geometry SHA-256")
    if (
        not terrain.get("terrain_version")
        or coverage.get("terrain_version") != terrain["terrain_version"]
    ):
        raise ValueError("Coverage terrain version does not match the terrain manifest")
    if coverage.get("stationCount") != model["counts"]["stations"]:
        raise ValueError("Coverage station count does not match the catalog")
    terrain_files = terrain.get("files")
    required_files = {
        f"{cloud}/{name}"
        for cloud in ["kozia", "regional"]
        for name in ["metadata.json", "hierarchy.bin", "octree.bin"]
    }
    if (
        not isinstance(terrain_files, dict)
        or not required_files <= terrain_files.keys()
    ):
        raise ValueError("Incomplete terrain file manifest")
    for record in terrain_files.values():
        check_record(record)
    verify_tree(output / "data", terrain_files)
    vendor_info = json.loads((ROOT / "vendor/potree-next.json").read_text())
    archive_path = ROOT / "vendor/potree-next.zip"
    if digest(archive_path) != vendor_info["archive_sha256"]:
        raise ValueError("Vendor checksum mismatch")
    vendor = output / "vendor/potree-next"
    if vendor.exists():
        shutil.rmtree(vendor)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = Path(*Path(member.filename).parts[1:])
            if member.is_dir() or str(relative) == ".":
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe vendor path")
            destination = vendor / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/patch_vendor.py"),
            "--output",
            str(output),
        ],
        check=True,
    )
    for name in ["jktz.html", "jktz.js"]:
        shutil.copyfile(ROOT / "app" / name, vendor / name)
    shutil.copyfile(ROOT / "app/index.html", output / "index.html")
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE")
    model.pop("stations")
    (output / "data/caves.json").write_text(
        json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    )
    (output / "inputs.json").write_text(
        json.dumps(inputs, ensure_ascii=False, indent=2) + "\n"
    )
    publication = {
        "schemaVersion": 1,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "repository": "https://github.com/dlubom/jktz-mapa-3d",
        "catalog": model["source"],
        "counts": model["counts"],
        "terrain": terrain,
        "coverage": coverage,
        "potreeNext": vendor_info,
    }
    (output / "publication.json").write_text(
        json.dumps(publication, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "SOURCE.md").write_text(
        "# Źródła aplikacji\n\nhttps://github.com/dlubom/jktz-mapa-3d\n\n"
        "Kod i lokalne poprawki Potree-Next: AGPL-3.0. Dane mają oddzielne licencje — "
        "zobacz README i publication.json.\n"
    )
    (output / ".nojekyll").write_text("")
    files = {
        str(p.relative_to(output)): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "checksums.json"
    }
    if sum(row["bytes"] for row in files.values()) >= 1_000_000_000:
        raise ValueError("Site exceeds the 1 GB Pages budget")
    (output / "checksums.json").write_text(
        json.dumps({"files": files}, indent=2) + "\n"
    )
    return verify(output)


def verify(output):
    output = Path(output)
    expected = json.loads((output / "checksums.json").read_text())["files"]
    actual = {
        str(p.relative_to(output))
        for p in output.rglob("*")
        if p.is_file() and p.name != "checksums.json"
    }
    if actual != set(expected):
        raise ValueError("Site file inventory mismatch")
    for name, row in expected.items():
        path = output / name
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"Site checksum mismatch: {name}")
    return {
        "files": len(expected),
        "bytes": sum(x["bytes"] for x in expected.values()),
        "status": "PASS",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    builder = sub.add_parser("build")
    builder.add_argument("--caves", type=Path, default=Path(".build/caves.json"))
    builder.add_argument("--inputs", type=Path, default=Path(".build/inputs.json"))
    builder.add_argument("--terrain", type=Path, default=Path("data/terrain.json"))
    builder.add_argument("--output", type=Path, default=Path("dist"))
    builder.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "local"))
    checker = sub.add_parser("verify")
    checker.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    result = (
        build(args.caves, args.inputs, args.terrain, args.output, args.commit)
        if args.command == "build"
        else verify(args.output)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
