"""Create a reviewable, read-only AG32 qualification intake report."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re

from . import __version__
from . import diagnostics


SCHEMA = 1
SUPPORT_MATRIX = Path(__file__).resolve().parent / "sdk" / "support_matrix.json"


_HOME_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:(?:[/\\]+)(?:Users|DOCUME~\d)(?:[/\\]+)[^/\\\s\"']+"),
    re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\s\"']+"),
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_support_matrix():
    data = json.loads(SUPPORT_MATRIX.read_text(encoding="utf-8"))
    dimensions = data.get("dimensions", {})
    required = {"part", "package", "board", "transport", "feature"}
    if data.get("schema") != 1 or set(dimensions) != required:
        raise ValueError("packaged support matrix has an unsupported schema")
    return data


def _portable_artifact_label(value, resolved):
    """Return a reviewable artifact label without a host-specific root."""
    original = Path(value)
    if not original.is_absolute():
        normalized = Path(os.path.normpath(str(original)))
        if normalized.parts and normalized.parts[0] != "..":
            return normalized.as_posix()
    try:
        relative = resolved.relative_to(Path.cwd().resolve())
    except ValueError:
        return resolved.name
    return relative.as_posix()


def _redact_host_paths(value):
    """Remove user-home identities from nested diagnostic/report strings."""
    if isinstance(value, dict):
        return {key: _redact_host_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_host_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_host_paths(item) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for pattern in _HOME_PATTERNS:
        result = pattern.sub("<HOME>", result)
    return result


def build_report(artifacts=(), notes=None):
    """Collect host facts and artifact hashes without opening an AG32 target."""
    artifact_records = []
    for value in artifacts:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"qualification artifact not found: {path}")
        artifact_records.append({
            "path": _portable_artifact_label(value, path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })

    matrix_bytes = SUPPORT_MATRIX.read_bytes()
    return {
        "schema": SCHEMA,
        "kind": "agamemnon-qualification-intake",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "target_io": False,
            "target_state_written": False,
            "detail": "Host tools are inspected and serial devices enumerated; no target transport is opened. The optional output JSON is the only host file written.",
        },
        "agamemnon_version": __version__,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "privacy": {
            "portable_paths": True,
            "detail": "Artifact labels omit host roots; user-home paths in diagnostics and notes are replaced by <HOME>.",
        },
        "doctor": _redact_host_paths(diagnostics.collect(hardware=False)),
        "support_matrix": {
            "path": "agamemnon/sdk/support_matrix.json",
            "sha256": hashlib.sha256(matrix_bytes).hexdigest(),
            "data": load_support_matrix(),
        },
        "artifacts": artifact_records,
        "notes": _redact_host_paths(notes or ""),
    }


def cmd_qualify(args):
    report = build_report(artifacts=args.artifact, notes=args.notes)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)
    else:
        print(text, end="")
