"""Read back exact deployed bytes, pinned catalogue inputs and HTTP Range."""

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
        return response.status, response.headers, response.read()


def confirm(url, commit, expected_inputs, model_sha, publication_sha, attempts=24):
    url = url.rstrip("/") + "/"
    catalog = expected_inputs["catalog"]
    expected_source = {
        "version": catalog["release"]["tag"],
        "releaseId": catalog["release"]["id"],
        "releaseUrl": catalog["release"]["url"],
        "assetId": catalog["asset"]["id"],
        "assetName": catalog["asset"]["name"],
        "assetSHA256": catalog["asset"]["sha256"],
    }
    query = "?" + urlencode({"sha": commit, "publication": publication_sha})
    last_error = None
    for attempt in range(attempts):
        try:
            _, _, body = read(url + "publication.json" + query)
            if hashlib.sha256(body).hexdigest() != publication_sha:
                raise ValueError(
                    "Public publication checksum is not the built artifact"
                )
            publication = json.loads(body)
            if publication["commit"] != commit:
                raise ValueError("Public commit mismatch")
            if any(
                publication["catalog"].get(k) != v for k, v in expected_source.items()
            ):
                raise ValueError("Public catalog does not match pinned release inputs")
            _, _, body = read(url + "inputs.json" + query)
            if json.loads(body) != expected_inputs:
                raise ValueError("Public inputs do not match pinned build inputs")
            _, _, model_bytes = read(url + "data/caves.json" + query)
            if hashlib.sha256(model_bytes).hexdigest() != model_sha:
                raise ValueError("Public model checksum is not the built artifact")
            caves = json.loads(model_bytes)
            if (
                caves["source"] != publication["catalog"]
                or caves["counts"] != publication["counts"]
            ):
                raise ValueError("Public catalog provenance mismatch")
            _, _, body = read(url + "checksums.json" + query)
            checksums = json.loads(body)["files"]
            if checksums["data/caves.json"]["sha256"] != model_sha:
                raise ValueError("Public checksum inventory mismatch")
            for name in ["kozia", "regional"]:
                status, headers, fragment = read(
                    url + f"data/{name}/octree.bin", {"Range": "bytes=0-31"}
                )
                total = publication["terrain"]["files"][f"{name}/octree.bin"]["bytes"]
                if (
                    status != 206
                    or len(fragment) != 32
                    or headers.get("Content-Range") != f"bytes 0-31/{total}"
                ):
                    raise ValueError(f"Public Range mismatch for {name}")
            return {
                "status": "PASS",
                "url": url,
                "commit": commit,
                "catalog": publication["catalog"],
                "counts": publication["counts"],
                "modelSHA256": model_sha,
                "publicationSHA256": publication_sha,
            }
        except (OSError, ValueError, KeyError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(5)
    raise ValueError(f"Public verification failed: {last_error}") from last_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--model-sha", required=True)
    parser.add_argument("--publication-sha", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            confirm(
                args.url,
                args.commit,
                json.loads(args.inputs.read_text()),
                args.model_sha,
                args.publication_sha,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
