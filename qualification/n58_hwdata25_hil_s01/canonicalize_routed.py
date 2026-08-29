#!/usr/bin/env python3
"""Canonicalize one N5.8A HIL routed checkpoint for fresh checkouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class CanonicalizationError(RuntimeError):
    pass


def _prefixes() -> tuple[str, ...]:
    windows = ROOT.as_posix().rstrip("/") + "/"
    drive = ROOT.drive.rstrip(":").lower()
    tail = ROOT.as_posix().split(":", 1)[1].lstrip("/")
    wsl = "/mnt/%s/%s/" % (drive, tail)
    return windows, wsl


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace("\\", "/")
    for prefix in _prefixes():
        normalized = normalized.replace(prefix, "")
    return normalized


def canonicalize(source: Path, destination: Path) -> None:
    document = json.loads(source.read_text(encoding="utf-8"))
    if set(document.get("modules", {})) != {"top"}:
        raise CanonicalizationError("routed checkpoint must contain only modules['top']")
    cleaned = _clean(document)
    encoded = json.dumps(cleaned, indent=2, sort_keys=True) + "\n"
    forbidden = ("/mnt/", "C:/Users/", "C:\\Users\\", "Benchoff")
    leaked = [token for token in forbidden if token in encoded]
    if leaked:
        raise CanonicalizationError(
            "routed checkpoint retains workstation identity: %s" % leaked
        )
    destination.write_text(encoded, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    canonicalize(args.source, args.destination)


if __name__ == "__main__":
    main()
