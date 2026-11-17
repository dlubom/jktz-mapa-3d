"""Build the regional Potree cloud from NMT 2019 and DMR 5.0 in EVRF2007."""

import argparse
import gzip
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from osgeo import gdal
from pyproj import Transformer

from pack_terrain import file_record, write_bundle
from prepare_nmt2019 import native_grid, write_cloud, write_json
from terrain import (
    load_manifest,
    load_mask,
    sha256,
    tree_path,
    verify_file,
    verify_tree,
)

VERSION = "terrain-v3"


def read_raster(path):
    with gdal.Open(str(path)) as raster:
        gt = raster.GetGeoTransform()
        if gt[2] or gt[4] or gt[1] <= 0 or gt[5] >= 0:
            raise ValueError(f"Unsupported raster axes: {path.name}")
        values = raster.GetRasterBand(1).ReadAsArray().astype(np.float64)
        nodata = raster.GetRasterBand(1).GetNoDataValue()
        values[(values == nodata) | ~np.isfinite(values)] = np.nan
        return values, gt, raster.GetSpatialRef().GetAuthorityCode(None)


def centers(gt, rows, cols):
    return gt[0] + (cols + 0.5) * gt[1], gt[3] + (rows + 0.5) * gt[5]


def grid_coords(gt, x, y):
    return (y - gt[3]) / gt[5], (x - gt[0]) / gt[1]


def nearest(data, gt, x, y):
    row, col = grid_coords(gt, x, y)
    r, c = np.floor(row).astype(int), np.floor(col).astype(int)
    inside = (r >= 0) & (c >= 0) & (r < data.shape[0]) & (c < data.shape[1])
    result = np.full(r.shape, np.nan)
    result[inside] = data[r[inside], c[inside]]
    return result


def bilinear(data, gt, x, y):
    row, col = grid_coords(gt, x, y)
    row, col = row - 0.5, col - 0.5
    r, c = np.floor(row).astype(int), np.floor(col).astype(int)
    inside = (r >= 0) & (c >= 0) & (r + 1 < data.shape[0]) & (c + 1 < data.shape[1])
    result = np.full(r.shape, np.nan)
    fy, fx = row[inside] - r[inside], col[inside] - c[inside]
    r, c = r[inside], c[inside]
    result[inside] = (1 - fy) * ((1 - fx) * data[r, c] + fx * data[r, c + 1]) + fy * (
        (1 - fx) * data[r + 1, c] + fx * data[r + 1, c + 1]
    )
    return result


def to_evrf(dmr, gt, geoid_path):
    r, c = np.nonzero(np.isfinite(dmr))
    e, n = centers(gt, r, c)
    to_geographic = Transformer.from_crs("EPSG:3046", "EPSG:4258", always_xy=True)
    lon, lat = to_geographic.transform(e, n, errcheck=True)
    vertical = Transformer.from_pipeline(
        "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
        f"+step +inv +proj=vgridshift +grids={geoid_path.resolve()} +multiplier=1 "
        "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
    )
    raw = dmr[r, c]
    _, _, height = vertical.transform(lon, lat, raw, errcheck=True)

    # Check the PROJ operation against independent bilinear interpolation of the GTX.
    grid, grid_gt, _ = read_raster(geoid_path)
    check = np.linspace(0, len(raw) - 1, 256, dtype=int)
    expected = raw[check] - bilinear(grid, grid_gt, lon[check], lat[check])
    error = float(np.max(np.abs(height[check] - expected)))
    if not np.isfinite(error) or error > 1e-6:
        raise ValueError(
            "PROJ EVRF2007 conversion differs from h minus the official quasigeoid"
        )
    converted = np.full_like(dmr, np.nan)
    converted[r, c] = height
    shifts = height - raw
    return converted, {
        "operation": "EPSG:8362, H(EVRF2007) = h(ETRS89) - DMQSK2014-E(lon, lat)",
        "valid_input_cells": len(raw),
        "shift_range_m": [float(shifts.min()), float(shifts.max())],
        "gtx_check_points": len(check),
        "gtx_check_max_abs_error_m": error,
    }


def residuals(x, y, nmt, dmr):
    differences = dmr - nmt
    if not len(differences):
        raise ValueError("No common samples for seam verification")
    quantiles = np.quantile(differences, [0, 0.05, 0.5, 0.95, 1]).tolist()

    def example(i):
        return {
            "epsg2180": [float(x[i]), float(y[i])],
            "dmr_minus_nmt_m": float(differences[i]),
            "nmt_m": float(nmt[i]),
            "dmr_m": float(dmr[i]),
        }

    return {
        "count": len(differences),
        "min_p05_median_p95_max_m": quantiles,
        "p95_abs_m": float(np.quantile(np.abs(differences), 0.95)),
        "rmse_m": float(np.sqrt(np.mean(differences**2))),
        "lowest": example(np.argmin(differences)),
        "highest": example(np.argmax(differences)),
    }


def compare_seam(nmt, nmt_gt, dmr, dmr_gt, target, inverse):
    # Limit the Polish sample grid to the bounds of the DMR 5.0 patch.
    geo = target["geotransform"]
    min_x, max_y = geo[0], geo[3]
    max_x = min_x + target["width"] * geo[1]
    min_y = max_y + target["height"] * geo[5]
    row0, col0 = np.floor(grid_coords(nmt_gt, min_x, max_y)).astype(int)
    row1, col1 = np.ceil(grid_coords(nmt_gt, max_x, min_y)).astype(int)
    if not (1 <= row0 < row1 < nmt.shape[0] and 1 <= col0 < col1 < nmt.shape[1]):
        raise ValueError("DMR comparison extent must be inside the NMT grid")
    r, c = np.nonzero(np.isfinite(nmt[row0:row1, col0:col1]))
    r, c = r + row0, c + col0
    x, y = centers(nmt_gt, r, c)
    e, n = inverse.transform(x, y, errcheck=True)
    sk = bilinear(dmr, dmr_gt, e, n)
    valid = np.isfinite(sk)
    edge = valid & ~(
        np.isfinite(nmt[r - 1, c])
        & np.isfinite(nmt[r + 1, c])
        & np.isfinite(nmt[r, c - 1])
        & np.isfinite(nmt[r, c + 1])
    )
    return {
        "method": "DMR minus NMT at the same Polish NMT cell centre; bilinear DMR with four valid native neighbours",
        "edge_definition": "Valid NMT cell next to a NoData NMT cell in four-neighbour connectivity",
        "overlap": residuals(x[valid], y[valid], nmt[r[valid], c[valid]], sk[valid]),
        "nmt_edge": residuals(x[edge], y[edge], nmt[r[edge], c[edge]], sk[edge]),
    }


def prepare(args):
    gdal.UseExceptions()
    sources = json.loads(args.manifest.read_text())
    base = load_manifest(args.base_manifest)
    if base["terrain_version"] != "terrain-v2":
        raise ValueError("DMR 5.0 requires the terrain-v2 base")
    verify_tree(args.base, base["files"])
    for key in ("dmr", "quasigeoid"):
        verify_file(args.dmr_sources / sources[key]["name"], sources[key])

    output = args.output / "data"
    output.mkdir(parents=True, exist_ok=False)
    record = sources["quasigeoid"]
    geoid = args.output / record["grid"]["name"]
    with zipfile.ZipFile(args.dmr_sources / record["name"]) as archive:
        with archive.open(geoid.name) as origin, geoid.open("xb") as sink:
            shutil.copyfileobj(origin, sink)
    verify_file(geoid, record["grid"])

    nmt_manifest = args.base / "provenance/nmt2019-sources.json"
    args.nmt_sources.mkdir(parents=True, exist_ok=True)
    nmt, _ = native_grid(json.loads(nmt_manifest.read_text()), args.nmt_sources)
    main_mask, original_bits = load_mask(args.base)
    valid_nmt = np.isfinite(nmt)
    if np.packbits(valid_nmt, bitorder="big").tobytes() != original_bits:
        raise ValueError(
            "Reconstructed NMT 2019 differs from the published validity mask"
        )
    nmt_gt = main_mask["geotransform"]

    dmr, dmr_gt, auth = read_raster(args.dmr_sources / sources["dmr"]["name"])
    if auth != "3046" or dmr_gt[1::4] != (1.0, -1.0):
        raise ValueError("DMR must be the native 1 m EPSG:3046 raster")
    converted, vertical_report = to_evrf(dmr, dmr_gt, geoid)
    target = sources["target_grid"]
    inverse = Transformer.from_crs(target["crs"], sources["dmr"]["crs"], always_xy=True)
    seam = compare_seam(nmt, nmt_gt, converted, dmr_gt, target, inverse)

    gt = target["geotransform"]
    r, c = np.indices((target["height"], target["width"]))
    x, y = centers(gt, r, c)
    e, n = inverse.transform(x, y, errcheck=True)
    sk = nearest(converted, dmr_gt, e, n)
    valid_sk = np.isfinite(sk) & ~np.isfinite(nearest(nmt, nmt_gt, x, y))
    nmt_x, nmt_y = centers(nmt_gt, *np.nonzero(valid_nmt))
    east = np.concatenate((nmt_x, x[valid_sk]))
    north = np.concatenate((nmt_y, y[valid_sk]))
    height = np.concatenate((nmt[valid_nmt], sk[valid_sk]))
    options = write_cloud(
        output,
        "tatry",
        "tatry-nmt2019-dmr5",
        target["crs"],
        args.converter.resolve(),
        east,
        north,
        height,
    )

    packed = np.packbits(valid_sk, bitorder="big").tobytes()
    mask = output / "dmr5-mask.bin.gz"
    mask.write_bytes(gzip.compress(packed, mtime=0))
    write_json(
        output / "dmr5-mask.json",
        {
            "schema_version": 1,
            "terrain_version": VERSION,
            "vertical_datum": "EVRF2007 (EPSG:5621)",
            "encoding": "row-major-msb-first-bitpack-gzip",
            "file": mask.name,
            **target,
            "valid_cells": int(valid_sk.sum()),
            "uncompressed_bytes": len(packed),
            "uncompressed_sha256": hashlib.sha256(packed).hexdigest(),
            "compressed": file_record(mask),
        },
    )
    write_json(
        output / "terrain-mask.json",
        {
            **main_mask,
            "terrain_version": VERSION,
            "source": "NMT 2019 + DMR 5.0",
            "supplement_mask": "dmr5-mask.json",
        },
    )
    write_json(
        output / "dmr5-provenance.json",
        {
            "source_manifest": "provenance/dmr5-sources.json",
            "vertical": vertical_report,
            "sampling": "Nearest native DMR cell on the 1 m EPSG:2180 grid, only outside valid 5 m NMT 2019 cells",
            "nmt_points": int(valid_nmt.sum()),
            "dmr_points": int(valid_sk.sum()),
            "converter_options": options,
            "converter_sha256": sha256(args.converter),
            "seam": seam,
        },
    )

    files = {
        name: tree_path(args.base, name)
        for name in base["files"]
        if not name.startswith("nmt2019/") and name != "terrain-mask.json"
    }
    for name in (
        "terrain-mask.json",
        "dmr5-mask.json",
        "dmr5-mask.bin.gz",
        "dmr5-provenance.json",
        "tatry/metadata.json",
        "tatry/hierarchy.bin",
        "tatry/octree.bin",
    ):
        files[name] = output / name
    files["provenance/dmr5-sources.json"] = args.manifest
    for key in ("dmr", "quasigeoid"):
        name = sources[key]["name"]
        files[f"provenance/dmr5/{name}"] = args.dmr_sources / name
    clouds = {key: value for key, value in base["clouds"].items() if key != "nmt2019"}
    clouds["tatry"] = {
        "metadata": "tatry/metadata.json",
        "points": len(height),
        "source": "GUGiK NMT 2019 with GKÚ DMR 5.0 in NoData, EVRF2007",
    }
    write_bundle(args.output / "release", VERSION, files, clouds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/dmr5-sources.json"))
    for name in (
        "base",
        "base-manifest",
        "dmr-sources",
        "nmt-sources",
        "output",
        "converter",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    prepare(parser.parse_args())
