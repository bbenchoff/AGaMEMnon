#!/usr/bin/env python3
"""Validate maintained Markdown links, local targets, and heading anchors."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path


INLINE_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+['\"].*?['\"])?\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:(?!:)\s*(<[^>]+>|\S+)", re.MULTILINE)
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
EXPLICIT_ID = re.compile(r"\b(?:id|name)=[\"']([^\"']+)[\"']", re.IGNORECASE)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def repository_markdown(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=str(root),
    )
    return sorted(root / Path(item.decode("utf-8")) for item in output.split(b"\0") if item)


def _anchor_name(heading: str) -> str:
    heading = re.sub(r"<[^>]*>", "", heading)
    heading = re.sub(r"[`*_~]", "", heading).strip().lower()
    heading = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE)
    return re.sub(r"\s+", "-", heading)


def anchors(text: str) -> set[str]:
    result = set(EXPLICIT_ID.findall(text))
    occurrences: dict[str, int] = defaultdict(int)
    for match in HEADING.finditer(text):
        base = _anchor_name(match.group(1))
        suffix = occurrences[base]
        occurrences[base] += 1
        result.add(base if suffix == 0 else f"{base}-{suffix}")
    return result


def link_targets(text: str) -> list[str]:
    result = [match.group(1) for match in INLINE_LINK.finditer(text)]
    result.extend(match.group(1) for match in REFERENCE_LINK.finditer(text))
    return [target[1:-1] if target.startswith("<") and target.endswith(">") else target
            for target in result]


def check_documents(root: Path, paths: list[Path]) -> list[str]:
    errors: list[str] = []
    text_cache: dict[Path, str] = {}
    anchor_cache: dict[Path, set[str]] = {}
    for source in paths:
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{source.relative_to(root)}: cannot read UTF-8 Markdown: {exc}")
            continue
        text_cache[source.resolve()] = text
        for target in link_targets(text):
            if not target or target.startswith(("#", "//")) or SCHEME.match(target):
                if target.startswith("#") and target[1:]:
                    anchor_cache.setdefault(source.resolve(), anchors(text))
                    if urllib.parse.unquote(target[1:]).lower() not in anchor_cache[source.resolve()]:
                        errors.append(f"{source.relative_to(root)}: missing local anchor {target}")
                continue
            path_part, separator, fragment = target.partition("#")
            path_part = urllib.parse.unquote(path_part.split("?", 1)[0])
            destination = (source.parent / path_part).resolve()
            try:
                destination.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{source.relative_to(root)}: local link escapes repository: {target}")
                continue
            if not destination.exists():
                errors.append(f"{source.relative_to(root)}: missing local target: {target}")
                continue
            if fragment and destination.suffix.lower() in (".md", ".markdown"):
                try:
                    destination_text = text_cache.setdefault(
                        destination, destination.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError) as exc:
                    errors.append(f"{source.relative_to(root)}: cannot inspect {target}: {exc}")
                    continue
                destination_anchors = anchor_cache.setdefault(destination, anchors(destination_text))
                if urllib.parse.unquote(fragment).lower() not in destination_anchors:
                    errors.append(f"{source.relative_to(root)}: missing anchor in {target}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="specific Markdown files (default: maintained repository Markdown)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    paths = [path if path.is_absolute() else root / path for path in args.paths]
    paths = paths or repository_markdown(root)
    errors = check_documents(root, paths)
    for error in errors:
        print(error)
    if errors:
        print(f"documentation check failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"documentation check passed: {len(paths)} Markdown page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
