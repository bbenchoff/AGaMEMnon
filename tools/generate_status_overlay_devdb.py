#!/usr/bin/env python3
"""Freeze the two strict-device tables needed by the installed status overlay."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
OUTPUT = ROOT / "agamemnon" / "engine"
TABLES = ("dev_pips.csv", "dev_belpins.csv")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def generate(source, output=OUTPUT):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "kind": "status-overlay-strict-devdb-gzip-v1", "tables": {}}
    for name in TABLES:
        raw = (source / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        artifact = output / ("status_overlay_" + name + ".gz")
        artifact.write_bytes(compressed)
        manifest["tables"][name] = {
            "source_sha256": sha(raw),
            "source_bytes": len(raw),
            "artifact": artifact.name,
            "artifact_sha256": sha(compressed),
            "artifact_bytes": len(compressed),
        }
    path = output / "status_overlay_devdb_manifest.json"
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    generate(args.source)


if __name__ == "__main__":
    main()
