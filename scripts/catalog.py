"""Pin and build the current stable JKTZ catalogue without changing survey Z.

Python 3.12+, pyproj and Survex dump3d exactly 1.4.24 are required for a build.
Run from the repository root:
    python scripts/catalog.py resolve --output .build/inputs.json
    python scripts/catalog.py build --inputs .build/inputs.json \
        --cache .cache/catalog --output .build/caves.json

The input contract is schemaVersion=1, catalog.repository, catalog.release
{id,tag,url,publishedAt}, catalog.asset {id,name,url,size,sha256}, catalog.resolvedAt.
An existing valid pin is reused without another latest-release request. A new
build directory is necessary to resolve a new stable release.

The output is absolute EPSG:2180 XYZ, origin=[566000,153000,0], source provenance,
dynamic counts/bounds/groups/stations, and controls=[]. Every NODE and LEG remains,
including anonymous stations, unscoped, surface, duplicate and splay legs. Source Z
is unchanged; its datum is not inferred from terrain. XYZ rendering translation is
the viewer's responsibility. All .3d members must be byte-identical if aliases are
present; unsafe ZIP paths, missing API digests, checksum/size failures, unknown CRS
and incomplete dump3d output stop the build instead of producing a partial result.
"""

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = "dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ORIGIN = [566000, 153000, 0]
REQUIRED_SURVEX_VERSION = "1.4.24"
VERTICAL_DATUM = (
    "Original compiled JKTZ Z preserved unchanged; vertical-datum provenance "
    "of the complete release is not established. No terrain fitting or height shift."
)


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, encoding="utf-8", delete=False
    ) as file:
        temporary = Path(file.name)
        json.dump(
            data, file, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        file.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_inputs(inputs):
    """Validate the immutable release/asset pin; return the input unchanged."""
    try:
        item = inputs["catalog"]
        release, asset = item["release"], item["asset"]
        tag = release["tag"]
        valid = (
            inputs["schemaVersion"] == 1
            and item["repository"] == REPOSITORY
            and isinstance(tag, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", tag)
            and release["url"] == f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
            and isinstance(release["publishedAt"], str)
            and asset["name"] == f"JKTZ-{tag}.zip"
            and asset["url"]
            == f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset['name']}"
            and re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
            and all(
                type(value) is int and value > 0
                for value in [release["id"], asset["id"], asset["size"]]
            )
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Invalid catalogue release/asset pin")
    return inputs


def resolve_inputs(output):
    """Resolve GitHub's latest stable release exactly once for this build."""
    output = Path(output)
    if output.exists():
        return validate_inputs(json.loads(output.read_text(encoding="utf-8")))
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "jktz-mapa-3d"},
    )
    if os.environ.get("GH_TOKEN"):
        # urllib intentionally omits unredirected headers from redirected requests.
        request.add_unredirected_header(
            "Authorization", f"Bearer {os.environ['GH_TOKEN']}"
        )
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Latest release is not a published stable release")
    tag = release.get("tag_name")
    assets = [
        asset
        for asset in release.get("assets", [])
        if asset.get("name") == f"JKTZ-{tag}.zip"
    ]
    if len(assets) != 1:
        raise ValueError("Expected exactly one matching JKTZ release ZIP asset")
    asset = assets[0]
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Release asset has no valid SHA-256 digest")
    inputs = {
        "schemaVersion": 1,
        "catalog": {
            "repository": REPOSITORY,
            "release": {
                "id": release["id"],
                "tag": tag,
                "url": release["html_url"],
                "publishedAt": release["published_at"],
            },
            "asset": {
                "id": asset["id"],
                "name": asset["name"],
                "url": asset["browser_download_url"],
                "size": asset["size"],
                "sha256": digest.removeprefix("sha256:"),
            },
            "resolvedAt": datetime.now(timezone.utc).isoformat(),
        },
    }
    validate_inputs(inputs)
    _write_json(output, inputs)
    return inputs


def _verify_asset(path, asset):
    if path.stat().st_size != asset["size"]:
        raise ValueError("Release asset size differs from the input pin")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != asset["sha256"]:
        raise ValueError("Release asset SHA-256 differs from the input pin")


def fetch_asset(asset, cache):
    """Fetch a public asset without credentials; verify fresh and cached bytes."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{asset['sha256']}.zip"
    if target.exists():
        _verify_asset(target, asset)
        return target
    temporary = None
    try:
        # No Authorization here, including when GitHub redirects to blob storage.
        request = urllib.request.Request(
            asset["url"], headers={"User-Agent": "jktz-mapa-3d"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            with tempfile.NamedTemporaryFile("wb", dir=cache, delete=False) as output:
                temporary = Path(output.name)
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > asset["size"]:
                        raise ValueError("Release asset size exceeds the input pin")
                    output.write(block)
        _verify_asset(temporary, asset)
        os.replace(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_model(archive):
    """Read one unambiguous compiled model; identical release aliases are valid."""
    with zipfile.ZipFile(archive) as package:
        seen = set()
        for info in package.infolist():
            name = info.filename
            parts = name.rstrip("/").split("/")
            if (
                name.startswith("/")
                or "\\" in name
                or ":" in parts[0]
                or any(part in {"", ".", ".."} for part in parts)
                or stat.S_ISLNK(info.external_attr >> 16)
                or name.casefold() in seen
            ):
                raise ValueError(f"Unsafe ZIP member: {name!r}")
            seen.add(name.casefold())
        candidates = [
            info
            for info in package.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".3d")
        ]
        if not candidates:
            raise ValueError("Release ZIP contains no compiled .3d model")
        candidates.sort(
            key=lambda info: (info.filename != "KATASTER.3d", info.filename)
        )
        name, model = None, None
        for info in candidates:
            if info.file_size > 256 * 1024 * 1024:
                raise ValueError("Compiled .3d model exceeds the 256 MiB safety limit")
            data = package.read(info)
            if model is not None and data != model:
                raise ValueError("Ambiguous release ZIP: compiled .3d models differ")
            if model is None:
                name, model = info.filename, data
        return name, model


def _bounds(points):
    return {
        "min": [min(point[i] for point in points) for i in range(3)],
        "max": [max(point[i] for point in points) for i in range(3)],
    }


def geometry_from_dump(dump, source):
    """Convert every dump3d --legs NODE/LEG; XY only, never adjust source Z."""
    from pyproj import Transformer

    lines = [line for line in dump.splitlines() if line.strip()]
    if not lines or lines[-1] != "STOP" or lines.count("STOP") != 1:
        raise ValueError("Incomplete dump3d output: expected final STOP")
    if [line for line in lines if line.startswith("CS ")] != ["CS EPSG:32634"]:
        raise ValueError("Expected compiled model CRS EPSG:32634")
    separators = [line for line in lines if line.startswith("SEPARATOR ")]
    if len(separators) != 1 or not re.fullmatch(r"SEPARATOR '(.)'", separators[0]):
        raise ValueError("Missing or invalid dump3d station separator")
    separator = re.fullmatch(r"SEPARATOR '(.)'", separators[0])[1]
    transform = Transformer.from_crs("EPSG:32634", "EPSG:2180", always_xy=True)

    def project(values):
        x, y, z = map(float, values)
        if not all(math.isfinite(value) for value in [x, y, z]):
            raise ValueError("Non-finite compiled model coordinate")
        easting, northing = transform.transform(x, y, errcheck=True)
        return [easting, northing, z]

    stations = []
    grouped = defaultdict(list)
    for line in lines:
        if line.startswith("NODE "):
            match = re.fullmatch(r"NODE (\S+) (\S+) (\S+) \[(.*?)\](.*)", line)
            if not match:
                raise ValueError(f"Malformed dump3d NODE: {line}")
            stations.append(
                {
                    "name": match[4],
                    "position": project(match.group(1, 2, 3)),
                    "flags": match[5].strip(),
                }
            )
        elif line.startswith("LEG "):
            match = re.fullmatch(
                r"LEG (\S+) (\S+) (\S+) (\S+) (\S+) (\S+) \[(.*?)\](.*)", line
            )
            if not match:
                raise ValueError(f"Malformed dump3d LEG: {line}")
            label = match[7]
            grouped[label.split(separator)[0]].append(
                {
                    "coordinates": project(match.group(1, 2, 3))
                    + project(match.group(4, 5, 6)),
                    "survey": label,
                    "flags": match[8].strip(),
                }
            )
        elif line.split()[0] not in {
            "TITLE",
            "DATE",
            "DATE_NUMERIC",
            "CS",
            "VERSION",
            "SEPARATOR",
            "--",
            "STOP",
            "ERROR_INFO",
            "XSECT",
            "XSECT_END",
        }:
            raise ValueError(f"Unexpected dump3d record (requires --legs): {line}")
    if not stations or not grouped:
        raise ValueError("Compiled model must contain stations and legs")
    groups = []
    unscoped_id = "_unscoped"
    while unscoped_id in grouped:
        unscoped_id = "_" + unscoped_id
    all_points = [station["position"] for station in stations]
    for prefix, legs in sorted(grouped.items()):
        coordinates = [leg["coordinates"] for leg in legs]
        endpoints = [row[index : index + 3] for row in coordinates for index in (0, 3)]
        all_points.extend(endpoints)
        groups.append(
            {
                "id": prefix or unscoped_id,
                "name": prefix or "Połączenia bez prefiksu",
                "sourcePrefix": prefix,
                "legs": coordinates,
                "legFlags": [leg["flags"] for leg in legs],
                "surveyLabels": [leg["survey"] for leg in legs],
                "bounds": _bounds(endpoints),
                "verticalDatum": VERTICAL_DATUM,
            }
        )
    return {
        "crs": "EPSG:2180",
        "axisOrder": "Easting, Northing, original model Z; metres",
        "verticalDatum": VERTICAL_DATUM,
        "origin": ORIGIN,
        "renderRule": (
            "Subtract origin from absolute XYZ before rendering; "
            "no other shift, scale or terrain fitting."
        ),
        "source": source,
        "counts": {
            "stations": len(stations),
            "legs": sum(len(group["legs"]) for group in groups),
            "groups": len(groups),
            "namedPrefixes": sum(bool(prefix) for prefix in grouped),
        },
        "bounds": _bounds(all_points),
        "groups": groups,
        "stations": stations,
        "controls": [],
    }


def build_catalog(inputs, cache, output):
    """Build caves.json from a verified pin, with dynamic counts and provenance."""
    from pyproj import __version__ as pyproj_version
    from pyproj import proj_version_str

    pin = validate_inputs(json.loads(Path(inputs).read_text(encoding="utf-8")))[
        "catalog"
    ]
    environment = dict(os.environ, LC_ALL="C")
    version = subprocess.run(
        ["dump3d", "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    ).stdout.strip()
    # 1.4.4 ignores the stored v8 separator; other versions need qualification.
    if version != f"dump3d - Survex {REQUIRED_SURVEX_VERSION}":
        raise ValueError(
            f"Qualified reader required: Survex {REQUIRED_SURVEX_VERSION}; "
            f"found {version!r}"
        )
    archive = fetch_asset(pin["asset"], cache)
    member, model = read_model(archive)
    with tempfile.TemporaryDirectory(prefix="jktz-catalog-") as work:
        compiled = Path(work) / "catalog.3d"
        compiled.write_bytes(model)
        dump = subprocess.run(
            ["dump3d", "--legs", str(compiled)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        ).stdout
    source = {
        "version": pin["release"]["tag"],
        "releaseUrl": pin["release"]["url"],
        "releaseId": pin["release"]["id"],
        "assetId": pin["asset"]["id"],
        "assetName": pin["asset"]["name"],
        "assetSHA256": pin["asset"]["sha256"],
        "model": member,
        "modelSHA256": hashlib.sha256(model).hexdigest(),
        "sourceCRS": "EPSG:32634",
        "dump3dVersion": version,
        "dumpSHA256": hashlib.sha256(dump.encode("utf-8")).hexdigest(),
        "pyprojVersion": pyproj_version,
        "projVersion": proj_version_str,
    }
    result = geometry_from_dump(dump, source)
    _write_json(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser(
        "resolve", help="Pin GitHub latest stable release once"
    )
    resolve.add_argument("--output", required=True, type=Path)
    build = commands.add_parser(
        "build", help="Build the pinned, checksum-verified geometry"
    )
    build.add_argument("--inputs", required=True, type=Path)
    build.add_argument("--cache", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            result = resolve_inputs(args.output)
            print(json.dumps(result["catalog"], ensure_ascii=False))
        else:
            result = build_catalog(args.inputs, args.cache, args.output)
            print(
                json.dumps(
                    {
                        "source": result["source"],
                        "counts": result["counts"],
                        "output": str(args.output),
                    },
                    ensure_ascii=False,
                )
            )
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Catalogue build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
