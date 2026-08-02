#!/usr/bin/env python3
"""Validate append-only qualification JSONL ledgers and their hash fields."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_path_leaks import PATTERNS


QUALIFICATION = ROOT / "qualification"
MANIFEST = QUALIFICATION / "evidence_manifest.json"
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_fields(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if "sha256" in key.lower():
                yield path, item
            yield from _hash_fields(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _hash_fields(item, f"{prefix}[{index}]")


def validate(root: Path = QUALIFICATION, manifest_path: Path = MANIFEST) -> list[str]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest: {exc}"]
    if manifest.get("schema") != 1 or manifest.get("policy") != "checked-prefix-append-only":
        return ["manifest: unsupported schema or policy"]
    entries = manifest.get("ledgers", {})
    if not isinstance(entries, dict):
        return ["manifest: ledgers must be an object"]
    actual = {path.name for path in root.glob("*.jsonl")}
    expected = set(entries)
    for name in sorted(actual - expected):
        errors.append(f"{name}: ledger is not declared in evidence_manifest.json")
    for name in sorted(expected - actual):
        errors.append(f"{name}: declared ledger is missing")

    exceptions = {
        (item.get("file"), item.get("trial_id"), item.get("field")): item
        for item in manifest.get("known_invalid_hashes", [])
    }
    observed_exceptions = set()
    total_records = 0
    for name in sorted(actual & expected):
        path = root / name
        data = path.read_bytes()
        entry = entries[name]
        prefix_bytes = entry.get("prefix_bytes")
        prefix_sha = entry.get("prefix_sha256")
        if not isinstance(prefix_bytes, int) or prefix_bytes < 0 or not SHA256.fullmatch(str(prefix_sha)):
            errors.append(f"{name}: invalid checked-prefix declaration")
            continue
        if len(data) < prefix_bytes:
            errors.append(f"{name}: ledger was truncated below its checked prefix")
        elif _hash(data[:prefix_bytes]) != prefix_sha.lower():
            errors.append(f"{name}: checked prefix changed; evidence must be append-only")
        if any(pattern.search(data) for pattern in PATTERNS):
            errors.append(f"{name}: contains a machine-specific home path")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{name}: not UTF-8 ({exc})")
            continue
        seen_lines = set()
        policy = entry.get("record_policy")
        if policy not in ("schema-1", "legacy-or-schema-1"):
            errors.append(f"{name}: unsupported record policy {policy!r}")
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if line in seen_lines:
                errors.append(f"{name}:{number}: duplicate evidence record")
            seen_lines.add(line)
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{name}:{number}: invalid JSON ({exc.msg})")
                continue
            if not isinstance(record, dict) or not record:
                errors.append(f"{name}:{number}: record must be a non-empty object")
                continue
            total_records += 1
            schema = record.get("schema")
            if policy == "schema-1" and schema != 1:
                errors.append(f"{name}:{number}: schema-1 ledger requires schema=1")
            elif policy == "legacy-or-schema-1" and schema not in (None, 1):
                errors.append(f"{name}:{number}: schema must be absent or 1")
            trial_id = record.get("trial_id")
            for field, value in _hash_fields(record):
                if isinstance(value, str) and SHA256.fullmatch(value):
                    continue
                key = (name, trial_id, field)
                if key in exceptions:
                    observed_exceptions.add(key)
                else:
                    errors.append(f"{name}:{number}: {field} is not a SHA-256 value")
    for key in sorted(set(exceptions) - observed_exceptions):
        errors.append(f"manifest: stale known-invalid-hash exception {key}")
    validate.records = total_records
    return errors


def main() -> int:
    errors = validate()
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"evidence gate passed: {len(json.loads(MANIFEST.read_text())['ledgers'])} ledgers, {validate.records} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
