import hashlib
import json

from agamemnon.engine.build_trace import write_attempt_trace


def test_recursive_fallback_and_repeated_runs_preserve_every_input(tmp_path):
    source = tmp_path / "mutable.json"
    snapshots = []
    for payload in (b'{"carry":"hard"}', b'{"carry":"lut"}', b'{"carry":"lut"}'):
        source.write_bytes(payload)
        path = write_attempt_trace(tmp_path / "trace", "attempt_01", source, {"seed": 1})
        snapshots.append((path, payload))
    assert len({path for path, _ in snapshots}) == 3
    for path, payload in snapshots:
        assert path.read_bytes() == payload
        record = json.loads(path.with_suffix(".meta.json").read_text())
        assert record == {"seed": 1, "input_snapshot": path.name,
                          "input_sha256": hashlib.sha256(payload).hexdigest()}
