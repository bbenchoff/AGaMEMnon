#!/usr/bin/env python3
"""Reject machine-specific absolute home paths in repository text files."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# Match ordinary and JSON-escaped Windows home paths plus POSIX home paths.
# System installation locations are intentionally allowed; the policy targets
# developer identity and workstation leakage.
PATTERNS = (
    re.compile(rb"(?i)(?<![A-Za-z0-9_])[A-Z]:(?:[/\\]|\\\\)+(?:Users|DOCUME~\d)(?:[/\\]|\\\\)+"),
    re.compile(rb"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\s\"']+/"),
)


def repository_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=str(root), stderr=subprocess.DEVNULL
    )
    return [root / Path(item.decode("utf-8")) for item in output.split(b"\0") if item]


def find_leaks(paths: list[Path]) -> list[tuple[Path, int, str]]:
    leaks: list[tuple[Path, int, str]] = []
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for number, line in enumerate(data.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                leaks.append((path, number, line.decode("utf-8", errors="replace").strip()))
    return leaks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="specific files (default: tracked and untracked repository files)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    paths = args.paths or repository_files(root)
    leaks = find_leaks([path if path.is_absolute() else root / path for path in paths])
    for path, line, content in leaks:
        try:
            shown = path.relative_to(root)
        except ValueError:
            shown = path
        print(f"{shown}:{line}: machine-specific absolute path: {content}")
    if leaks:
        print(f"path-leak policy failed: {len(leaks)} line(s)", file=sys.stderr)
        return 1
    print(f"path-leak policy passed: {len(paths)} file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
