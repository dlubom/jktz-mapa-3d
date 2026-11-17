#!/usr/bin/env python3
"""Fetch pinned terrain data and count native-raster coverage using only stdlib."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

BYTE_BITS = tuple(bin(value).count("1") for value in range(256))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or str(path) != name
    ):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return name


def check_record(record: dict) -> None:
    if not isinstance(record.get("bytes"), int) or record["bytes"] < 0:
        raise ValueError("Invalid byte count in terrain manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")):
        raise ValueError("Invalid SHA-256 in terrain manifest")


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not manifest.get("files"):
        raise ValueError("Unsupported or empty terrain manifest")
    check_record(manifest["archive"])
    for name, record in manifest["files"].items():
        safe_name(name)
        check_record(record)
    return manifest


def verify_file(path: Path, record: dict) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing file or symlink: {path}")
    if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
        raise ValueError(f"Size or SHA-256 mismatch: {path}")


def verify_tree(directory: Path, files: dict) -> None:
    for name, record in files.items():
        verify_file(tree_path(directory, name), record)


def tree_path(directory: Path, name: str) -> Path:
    """Reject links inside the chosen root, allowing OS aliases such as /var."""
    if directory.is_symlink():
        raise ValueError(f"Refusing symlink terrain root: {directory}")
    root = directory.resolve()
    path = root / safe_name(name)
    parent = path.parent
    while parent != root:
        if parent.is_symlink():
            raise ValueError(f"Refusing symlink inside terrain tree: {parent}")
        parent = parent.parent
    return path


def extract_verified(archive: Path, destination: Path, files: dict) -> None:
    """Validate the entire central directory before writing any archive entry."""
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = []
        for info in entries:
            name = safe_name(info.filename)
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
            ):
                raise ValueError(f"Unsupported archive entry: {name}")
            if info.flag_bits & 1:
                raise ValueError(f"Encrypted archive entry: {name}")
            if name not in files or info.file_size != files[name]["bytes"]:
                raise ValueError(f"Unexpected archive file or size: {name}")
            names.append(name)
        if len(names) != len(set(names)) or set(names) != set(files):
            raise ValueError("Duplicate, missing, or extra archive files")
        destination.mkdir(parents=True, exist_ok=True)
        for info in entries:
            path = destination / info.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, path.open("xb") as target:
                shutil.copyfileobj(source, target)
            verify_file(path, files[info.filename])


def copy_verified(source: Path, destination: Path, files: dict) -> None:
    """Publish only named terrain files; preserve separately generated caves.json."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, record in files.items():
        target = tree_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError(f"Refusing symlink output: {target}")
        handle, temporary_name = tempfile.mkstemp(prefix=".terrain-", dir=target.parent)
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source / name, temporary)
            verify_file(temporary, record)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def fetch(manifest_path: Path, cache: Path, output: Path) -> dict:
    manifest = load_manifest(manifest_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cached = False
    if cache.exists():
        try:
            verify_tree(cache, manifest["files"])
            cached = True
        except ValueError:
            pass
    if not cached:
        with tempfile.TemporaryDirectory(
            prefix="terrain-fetch-", dir=cache.parent
        ) as temporary:
            workspace = Path(temporary)
            archive = workspace / "terrain.zip"
            expected = manifest["archive"]["bytes"]
            received = 0
            with (
                urlopen(manifest["archive"]["url"], timeout=120) as response,
                archive.open("wb") as target,
            ):
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > expected:
                        raise ValueError("Terrain archive exceeds pinned byte count")
                    target.write(block)
            verify_file(archive, manifest["archive"])
            unpacked = workspace / "data"
            extract_verified(archive, unpacked, manifest["files"])
            copy_verified(unpacked, cache, manifest["files"])
    if cache.resolve() != output.resolve():
        copy_verified(cache, output, manifest["files"])
    verify_tree(output, manifest["files"])
    return {
        "terrain_version": manifest["terrain_version"],
        "cache_hit": cached,
        "verified_files": len(manifest["files"]),
        "output": str(output),
    }


def load_mask(directory: Path, name: str = "terrain-mask.json") -> tuple[dict, bytes]:
    metadata = json.loads(tree_path(directory, name).read_text(encoding="utf-8"))
    if (
        metadata.get("schema_version") != 1
        or metadata.get("encoding") != "row-major-msb-first-bitpack-gzip"
        or metadata.get("crs") != "EPSG:2180"
    ):
        raise ValueError("Unsupported native terrain mask")
    width, height = metadata["width"], metadata["height"]
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or width * height > 1_000_000_000
    ):
        raise ValueError("Invalid native terrain mask dimensions")
    transform = metadata["geotransform"]
    if (
        len(transform) != 6
        or not all(math.isfinite(v) for v in transform)
        or transform[1] <= 0
        or transform[5] >= 0
        or transform[2] != 0
        or transform[4] != 0
    ):
        raise ValueError("Unsupported native terrain mask transform")
    path = directory / safe_name(metadata["file"])
    verify_file(path, metadata["compressed"])
    expected = (width * height + 7) // 8
    with gzip.open(path, "rb") as stream:
        bits = stream.read(expected + 1)
    if (
        len(bits) != expected
        or hashlib.sha256(bits).hexdigest() != metadata["uncompressed_sha256"]
    ):
        raise ValueError("Native terrain mask size or SHA-256 mismatch")
    padding = 8 - width * height % 8
    if padding < 8 and bits[-1] & ((1 << padding) - 1):
        raise ValueError("Native terrain mask has nonzero padding bits")
    if sum(BYTE_BITS[value] for value in bits) != metadata["valid_cells"]:
        raise ValueError("Native terrain mask valid-cell count mismatch")
    return metadata, bits


def covered(metadata: dict, bits: bytes, x: float, y: float) -> bool:
    origin_x, dx, _, origin_y, _, dy = metadata["geotransform"]
    column, row = math.floor((x - origin_x) / dx), math.floor((y - origin_y) / dy)
    if not (0 <= column < metadata["width"] and 0 <= row < metadata["height"]):
        return False
    index = row * metadata["width"] + column
    return bool(bits[index // 8] & (1 << (7 - index % 8)))


def coverage(terrain_dir: Path, caves_path: Path, output: Path) -> dict:
    metadata, bits = load_mask(terrain_dir)
    comparison = None
    if "comparison_mask" in metadata:
        comparison = load_mask(terrain_dir, metadata["comparison_mask"])
        if comparison[0]["vertical_datum"] != metadata["vertical_datum"]:
            raise ValueError("Native terrain masks must use the same vertical datum")
    caves = json.loads(caves_path.read_text(encoding="utf-8"))
    if caves.get("crs") != metadata["crs"] or not isinstance(
        caves.get("stations"), list
    ):
        raise ValueError("Cave stations must use EPSG:2180 and contain a stations list")
    groups = {}
    count = 0
    old_count = added = lost = 0
    for station in caves["stations"]:
        position = station["position"]
        if len(position) != 3 or not all(
            isinstance(v, (int, float)) and math.isfinite(v) for v in position
        ):
            raise ValueError("Station position must contain three finite coordinates")
        good = covered(metadata, bits, position[0], position[1])
        count += good
        if comparison is not None:
            old = covered(*comparison, position[0], position[1])
            old_count += old
            added += good and not old
            lost += old and not good
        group = station.get("name", "").split(":")[0] or "_unscoped"
        item = groups.setdefault(group, {"stations": 0, "covered": 0})
        item["stations"] += 1
        item["covered"] += good
    total = len(caves["stations"])
    percent = count / total * 100 if total else 0.0
    area = (
        metadata["valid_cells"]
        * abs(metadata["geotransform"][1] * metadata["geotransform"][5])
        / 1e6
    )

    def number(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    def summarize(value: int) -> str:
        percentage = f"{value / total * 100 if total else 0:.1f}".replace(".", ",")
        return f"{number(value)} z {number(total)} stacji ({percentage}%)"

    summary = summarize(count)
    source = metadata.get("source", "ALS 2025")
    result = {
        "schema_version": 1,
        "terrain_version": metadata["terrain_version"],
        "crs": metadata["crs"],
        "vertical_datum": metadata["vertical_datum"],
        "caves_sha256": sha256(caves_path),
        "stations": {
            "total": total,
            "covered": count,
            "uncovered": total - count,
            "covered_percent": percent,
        },
        "stationCount": total,
        "coveredStations": count,
        "percent": percent,
        "summary": summary,
        "source": source,
        "groups": {
            "total": len(groups),
            "full": sum(v["covered"] == v["stations"] for v in groups.values()),
            "partial": sum(0 < v["covered"] < v["stations"] for v in groups.values()),
            "none": sum(v["covered"] == 0 for v in groups.values()),
        },
        "by_group": groups,
        "valid_native_area_km2": area,
        "method": (
            "Valid native NMT cell under each station XY; duplicate station records retained; "
            "no elevation accuracy claim"
        ),
        "description": (
            f"{source} obejmuje {summary}. Ważne komórki zajmują {area:.2f} km²."
        ),
    }
    if comparison is not None:
        result["als2025"] = {
            "coveredStations": old_count,
            "percent": old_count / total * 100 if total else 0.0,
            "summary": summarize(old_count),
            "additionalStations": added,
            "onlyAls2025Stations": lost,
        }
        result["description"] += (
            f" Regionalny NMT z ALS 2025 obejmuje {summarize(old_count)}."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("fetch")
    get.add_argument("--manifest", type=Path, required=True)
    get.add_argument("--cache", type=Path, required=True)
    get.add_argument("--output", type=Path, required=True)
    sample = commands.add_parser("coverage")
    sample.add_argument("--terrain-dir", type=Path, required=True)
    sample.add_argument("--caves", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        result = fetch(args.manifest, args.cache, args.output)
    else:
        result = coverage(args.terrain_dir, args.caves, args.output)
        result = {
            k: result[k]
            for k in ["terrain_version", "stations", "groups", "valid_native_area_km2"]
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
