"""Authenticated reproduction of retained pre-owner emission, never new designs."""
import hashlib
import json
from pathlib import Path
from agamemnon.engine.registry import OPTIONS, EngineOptions

OPTION = "AGAMEMNON_RETAINED_REPLAY"
PROFILE = "pre-owner-v1"
QUALIFIED_OPTION = "AGAMEMNON_QUALIFIED_RETAINED_REPLAY"
QUALIFIED_PROFILES = {
    "mcu-ahb-bank16-read-word0": {
        "routed_sha256": "1daa7de2d8a5297182b35c21d745900e93bb540bd4ca3320449108dccd3fbef2",
        "bitstream_sha256": "301edbab67a42edcfb958d4dda7f3ffba786d425123a7c27826fccfba6765160",
    },
    "mcu-ahb-bank16-public-scratch4": {
        "routed_sha256": "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610",
        "bitstream_sha256": "2aa4d1d65c57c1ae28612f5743b08a7683179786e2d467c20166add1fba60882",
    },
}
REGISTRY_SHA256 = "1115d38a900f328b8e1f1a89f767296b26db8f54f5aea5299148d974944c05b7"

def _selected_profile(options):
    if options is None:
        return None
    # Clock validation also accepts a plain options mapping.
    if not hasattr(options, "raw"):
        options = EngineOptions(options)
    value = options.raw("AGAMEMNON_RETAINED_REPLAY")
    qualified = options.raw("AGAMEMNON_QUALIFIED_RETAINED_REPLAY")
    if value not in (None, "") and qualified not in (None, ""):
        raise ValueError("legacy and qualified retained replay modes are mutually exclusive")
    if qualified not in (None, ""):
        if qualified not in QUALIFIED_PROFILES:
            raise ValueError("unknown qualified retained replay profile: %s" % qualified)
        return qualified
    if value in (None, ""):
        return None
    if value != PROFILE:
        raise ValueError("unknown retained replay version: %s" % value)
    return PROFILE


def enabled(options):
    """Whether either authenticated replay mode is selected."""
    return _selected_profile(options) is not None


def _load_registry(chipdb_root):
    raw = (Path(chipdb_root) / "retained_pre_owner_v1.json").read_bytes()
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if hashlib.sha256(raw).hexdigest() != REGISTRY_SHA256:
        raise ValueError("retained replay registry digest mismatch")
    registry = json.loads(raw)
    rows = registry["artifacts"]
    if len(rows) != 58:
        raise ValueError("retained replay registry count mismatch")
    return rows


def qualified_clock_identity(options, routed_sha256, module, chipdb_root):
    """Return an exact legacy clock identity for the closed qualified mode.

    This is deliberately unavailable to the general diagnostic replay option.
    Bitgen still calls :func:`authenticate` with the routed file before
    emission, which additionally binds its normalized file hash and recorded
    environment.
    """
    selected = _selected_profile(options)
    if selected not in QUALIFIED_PROFILES:
        return None
    expected = QUALIFIED_PROFILES[selected]
    module_hash = hashlib.sha256(json.dumps(
        module, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()).hexdigest()
    rows = _load_registry(chipdb_root)
    matches = [row for row in rows
               if row["routed_sha256"] == routed_sha256 and
               row["canonical_module_sha256"] == module_hash]
    if len(matches) != 1:
        raise ValueError("qualified retained replay requires its exact authenticated checkpoint")
    row = matches[0]
    if (row["routed_sha256"] != expected["routed_sha256"] or
            row["bitstream_sha256"] != expected["bitstream_sha256"]):
        raise ValueError("qualified retained replay profile does not bind this checkpoint/image pair")
    return row["bitstream_sha256"]


def authenticate(options, routed_path, module, chipdb_root):
    selected = _selected_profile(options)
    if selected is None:
        return None
    rows = _load_registry(chipdb_root)
    source = Path(routed_path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    source_hash = hashlib.sha256(source).hexdigest()
    module_hash = hashlib.sha256(json.dumps(module, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    matches = [r for r in rows if r["routed_sha256"] == source_hash and r["canonical_module_sha256"] == module_hash]
    if len(matches) != 1:
        raise ValueError("retained replay requires an exact authenticated original checkpoint")
    row = matches[0]
    if selected in QUALIFIED_PROFILES:
        expected = QUALIFIED_PROFILES[selected]
        if (row["routed_sha256"] != expected["routed_sha256"] or
                row["bitstream_sha256"] != expected["bitstream_sha256"]):
            raise ValueError("qualified retained replay profile does not bind this checkpoint/image pair")
    for key, value in row["environment"].items():
        actual = options.raw(key) if key in OPTIONS else options.environ.get(key)
        if str(actual) != str(value):
            raise ValueError("retained replay environment mismatch at %s" % key)
    return row["bitstream_sha256"]
