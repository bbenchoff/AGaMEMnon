"""Authenticated reproduction of retained pre-owner emission, never new designs."""
import hashlib
import json
from pathlib import Path
from agamemnon.engine.registry import OPTIONS

OPTION = "AGAMEMNON_RETAINED_REPLAY"
PROFILE = "pre-owner-v1"
REGISTRY_SHA256 = "1115d38a900f328b8e1f1a89f767296b26db8f54f5aea5299148d974944c05b7"

def enabled(options):
    value = options.raw("AGAMEMNON_RETAINED_REPLAY")
    if value in (None, ""):
        return False
    if value != PROFILE:
        raise ValueError("unknown retained replay version: %s" % value)
    return True

def authenticate(options, routed_path, module, chipdb_root):
    if not enabled(options):
        return None
    raw = (Path(chipdb_root) / "retained_pre_owner_v1.json").read_bytes()
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if hashlib.sha256(raw).hexdigest() != REGISTRY_SHA256:
        raise ValueError("retained replay registry digest mismatch")
    registry = json.loads(raw)
    rows = registry["artifacts"]
    if len(rows) != 58:
        raise ValueError("retained replay registry count mismatch")
    source = Path(routed_path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    source_hash = hashlib.sha256(source).hexdigest()
    module_hash = hashlib.sha256(json.dumps(module, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    matches = [r for r in rows if r["routed_sha256"] == source_hash and r["canonical_module_sha256"] == module_hash]
    if len(matches) != 1:
        raise ValueError("retained replay requires an exact authenticated original checkpoint")
    row = matches[0]
    for key, value in row["environment"].items():
        actual = options.raw(key) if key in OPTIONS else options.environ.get(key)
        if str(actual) != str(value):
            raise ValueError("retained replay environment mismatch at %s" % key)
    return row["bitstream_sha256"]
