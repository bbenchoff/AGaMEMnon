"""Create a reviewable, read-only AG32 qualification intake report."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

from . import __version__
from . import diagnostics


SCHEMA = 1
SUPPORT_MATRIX = Path(__file__).resolve().parent / "sdk" / "support_matrix.json"


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


def build_report(artifacts=(), notes=None):
    """Collect host facts and artifact hashes without opening an AG32 target."""
    artifact_records = []
    for value in artifacts:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"qualification artifact not found: {path}")
        artifact_records.append({
            "path": str(path),
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
        "doctor": diagnostics.collect(hardware=False),
        "support_matrix": {
            "path": "agamemnon/sdk/support_matrix.json",
            "sha256": hashlib.sha256(matrix_bytes).hexdigest(),
            "data": load_support_matrix(),
        },
        "artifacts": artifact_records,
        "notes": notes or "",
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
