"""Prepare the regional NMT 2019 cloud from pinned GUGiK ASCII grids."""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

import laspy
import numpy as np
from osgeo import gdal
from pyproj import CRS

from terrain import sha256, verify_file


def pinned_sheet(source_dir, record):
    url = record["url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "opendata.geoportal.gov.pl":
        raise ValueError(f"Unexpected GUGiK source URL: {url}")
    path = source_dir / Path(parsed.path).name
    if not path.exists():
        temporary = path.with_suffix(".part")
        try:
            with urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            verify_file(temporary, record)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    verify_file(path, record)
    return path


def native_grid(manifest, source_dir):
    grid = manifest["grid"]
    x0, step, _, y0, _, _ = grid["geotransform"]
    heights = np.full((grid["height"], grid["width"]), np.nan, dtype=np.float32)
    rejected = []
    for record in manifest["sheets"]:
        path = pinned_sheet(source_dir, record)
        with gdal.Open(str(path)) as dataset:
            x, dx, rx, y, ry, dy = dataset.GetGeoTransform()
            column, row = (x - x0) / step, (y0 - y) / step
            if (dx, rx, ry, dy) != (step, 0, 0, -step) or not (
                column.is_integer() and row.is_integer()
            ):
                raise ValueError(f"Unexpected native grid for {path.name}")
            values = dataset.ReadAsArray()
            valid = np.isfinite(values) & (
                values != dataset.GetRasterBand(1).GetNoDataValue()
            )
        column, row = int(column), int(row)
        left, top = max(0, column), max(0, row)
        right = min(grid["width"], column + values.shape[1])
        bottom = min(grid["height"], row + values.shape[0])
        if right <= left or bottom <= top:
            continue
        crop = np.s_[top - row : bottom - row, left - column : right - column]
        values, valid = values[crop], valid[crop]
        # Four isolated 0.165 m samples in the Tatras are invalid terrain.
        implausible = valid & (values < 500)
        for r, c in zip(*np.nonzero(implausible)):
            rejected.append(
                {
                    "sheet": record["sheet"],
                    "easting": x0 + (left + int(c) + 0.5) * step,
                    "northing": y0 - (top + int(r) + 0.5) * step,
                    "height": float(values[r, c]),
                }
            )
        valid &= ~implausible
        target = heights[top:bottom, left:right]
        if np.any(valid & np.isfinite(target)):
            raise ValueError(f"Overlapping valid cells in {path.name}")
        target[valid] = values[valid]
    return heights, rejected


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def prepare(manifest_path, source_dir, output, converter):
    gdal.UseExceptions()
    manifest = json.loads(manifest_path.read_text())
    source_dir.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    grid = manifest["grid"]
    x0, step, _, y0, _, _ = grid["geotransform"]
    heights, rejected = native_grid(manifest, source_dir)
    valid = np.isfinite(heights)
    rows, cols = np.nonzero(valid)
    elevation = heights[valid]
    count = len(elevation)
    packed = np.packbits(valid, bitorder="big").tobytes()
    mask = output / "nmt2019-mask.bin.gz"
    mask.write_bytes(gzip.compress(packed, mtime=0))
    write_json(
        output / "terrain-mask.json",
        {
            "schema_version": 1,
            "terrain_version": "terrain-v2",
            "source": "NMT 2019",
            "comparison_mask": "terrain-mask-als2025.json",
            "crs": manifest["crs"],
            "vertical_datum": manifest["vertical_datum"],
            "encoding": "row-major-msb-first-bitpack-gzip",
            "file": mask.name,
            **grid,
            "valid_cells": count,
            "uncompressed_bytes": len(packed),
            "uncompressed_sha256": hashlib.sha256(packed).hexdigest(),
            "compressed": {"bytes": mask.stat().st_size, "sha256": sha256(mask)},
        },
    )

    options = write_cloud(
        output,
        "nmt2019",
        "nmt2019-5m",
        manifest["crs"],
        converter,
        x0 + (cols + 0.5) * step,
        y0 - (rows + 0.5) * step,
        elevation,
    )
    write_json(
        output / "nmt2019-provenance.json",
        {
            "source_manifest": "data/nmt2019-sources.json",
            "source_manifest_sha256": sha256(manifest_path),
            "converter_commit": "c2cb61843bf2b901e8e257874b1a6dcf67792fb2",
            "converter_sha256": sha256(converter),
            "converter_options": options,
            "valid_native_cells": count,
            "height_range_m": [float(elevation.min()), float(elevation.max())],
            "excluded_samples_below_500_m": rejected,
        },
    )


def write_cloud(output, folder, name, crs, converter, east, north, elevation):
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.full(3, 0.001)
    header.add_crs(CRS.from_user_input(crs))
    cloud = laspy.LasData(header)
    cloud.x = east
    cloud.y = north
    cloud.z = elevation.astype(np.float64)
    knots = [800, 1300, 1650, 1900, 2400]
    colors = (
        [65, 96, 146, 178, 230],
        [95, 125, 145, 172, 230],
        [81, 90, 115, 156, 226],
    )
    for channel, shades in zip(("red", "green", "blue"), colors):
        cloud[channel] = (
            np.rint(np.interp(elevation, knots, shades)).astype(np.uint16) * 257
        )
    las = output.parent / f"{name}.las"
    cloud.write(las)
    options = [
        "--encoding",
        "DEFAULT",
        "--method",
        "poisson",
        "--projection",
        crs,
    ]
    subprocess.run(
        [str(converter), str(las), "-o", str(output / folder), *options],
        check=True,
    )
    metadata = json.loads((output / folder / "metadata.json").read_text())
    if metadata["points"] != len(elevation) or metadata["projection"] != crs:
        raise ValueError("Potree metadata does not match the native pixel count or CRS")
    return options


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/nmt2019-sources.json")
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.manifest, args.source_dir, args.output, args.converter.resolve())
