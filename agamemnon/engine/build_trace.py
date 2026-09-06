"""Immutable input snapshots for repeated and recursive build attempts."""
import hashlib
import json
from pathlib import Path
import tempfile


def write_attempt_trace(directory, stem, source, metadata):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    # Recursive synthesis fallbacks restart attempt numbering. An exclusive
    # unique filename preserves every input even when the rung name repeats.
    with tempfile.NamedTemporaryFile(prefix=stem + "_", suffix=".json",
                                     dir=directory, delete=False) as stream:
        stream.write(data)
        snapshot = Path(stream.name)
    record = dict(metadata, input_snapshot=snapshot.name,
                  input_sha256=hashlib.sha256(data).hexdigest())
    with snapshot.with_suffix(".meta.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return snapshot
