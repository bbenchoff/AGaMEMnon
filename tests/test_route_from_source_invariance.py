"""GAP-2 closure: from-source route-invariance ("from-source Rule 2").

Context (see AG32-Docs docs/TASK_QUEUE.md queue B task B3, and the "from-source
Rule 2" named in AG32-Docs docs/PROMOTION_TIER_AMENDMENT_PROPOSAL.md as T9):

``agamemnon.engine.routing_admission._real_route_invariance_check`` (D0 Rule 2)
proves a candidate chipdb change does not change the emitted BITSTREAM of a
retained qualified artifact -- but it does so by calling ``bitgen.build()``
against the artifact's *already-routed, pinned* JSON. It re-PACKS a frozen
netlist; it never asks nextpnr to place-and-route again. It is therefore
structurally blind to nextpnr choosing a genuinely *different route* for
*unchanged source* purely because the chipdb grew or its tables changed --
which is exactly what happened on 2026-08-18: ``mcu_ahb_constant_slave``'s
fresh route drifted onto the open X14Y8 RMUX->IMUX->RMUX detour with the
design's own ``cap=2 seed=4`` completely unchanged, and the resulting
bitstream was wrong on silicon (T22-T24; refuted-fix history in T26/A1b).

What this module DOES cover:
  * For each design registered in ``qualification/route_from_source_regression.json``,
    a genuinely fresh ``yosys`` synth + ``nextpnr-generic`` (agrv2k uarch)
    place-and-route from the checked-in Verilog source, against whatever
    chipdb is actually installed/checked out right now.
  * The resulting routed JSON is canonicalized (CRLF -> LF, exactly like
    ``tests/test_qualified_pack_regression.py``'s ``_canonical_lf``) and
    SHA-256'd, and that ROUTE hash is compared to the pin recorded in the
    registry -- not just the final bitstream hash.
  * Fails closed: a missing registry entry field, an unreadable source file,
    a source hash that no longer matches the pin, a build that cannot
    complete, or a route hash mismatch are ALL treated as failures. Nothing
    here silently downgrades to a pass.

What this module does NOT cover:
  * It is NOT the default-suite guard. It is skipped unless
    ``AGAMEMNON_TEST_FROM_SOURCE_ROUTE=1`` is set (see the module docstring
    reasoning: a real synth+route build is minutes per design, not
    milliseconds, so it must never run in the default ``pytest -q`` pass or
    in CI's per-push job). It also skips cleanly, like
    ``tests/test_build_e2e.py``, when yosys/nextpnr-generic (agrv2k uarch)
    are not available locally.
  * It covers only the small, hand-curated subset of designs listed in the
    registry -- currently one, ``mcu_ahb_constant_slave``, chosen because it
    is the exact design the 2026-08-18 incident was found on. It is not a
    substitute for D0 Rule 2 (which still gates the D0 default-promotion
    approval artifact specifically) and it is not a substitute for silicon
    re-verification: a route-hash MATCH here means "nextpnr reached the same
    route as last time," not "that route is correct on hardware."
  * It does not attempt to fix, work around, or blacklist the X14Y8 detour.
    That is AG32-Docs task B1, out of scope here. The ``mcu_ahb_constant_slave``
    case is expected, and marked, ``xfail`` for exactly that reason -- see
    the registry entry's ``known_open_defect_reference``. An unexpected
    XPASS is the signal that B1 has been fixed and the xfail marker (and the
    pin) should be reviewed, not silently removed.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "qualification" / "route_from_source_regression.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

OPTION = "AGAMEMNON_TEST_FROM_SOURCE_ROUTE"

# Purely tool-location configuration: safe (and necessary) to pass through
# from the ambient environment. Everything else AGAMEMNON_* is stripped and
# replaced by the registry entry's own declared build_environment, exactly
# like test_qualified_pack_regression.py strips ambient AGAMEMNON_* before
# overlaying an artifact's recorded environment -- so this check exercises
# the registered build parameters only, never whatever happens to be set in
# the calling shell.
_TOOL_LOCATION_VARS = (
    "AGAMEMNON_OSS", "AGAMEMNON_UARCH_NEXTPNR", "AGAMEMNON_UARCH_NEXTPNR_RUNTIME",
)


def _canonical_lf(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256_text(path):
    return hashlib.sha256(_canonical_lf(Path(path).read_bytes())).hexdigest()


def _sha256_bytes(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tool(name):
    """Locate an open-flow tool: $AGAMEMNON_OSS/bin first, then PATH.

    Mirrors tests/test_build_e2e.py's ``_tool`` helper.
    """
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            candidate = os.path.join(oss, "bin", name + ext)
            if os.path.exists(candidate):
                return candidate
    return shutil.which(name)


def _uarch_nextpnr():
    """Locate the agrv2k uarch nextpnr-generic build the real CLI would use."""
    configured = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if configured:
        first = configured.split()[0]
        if shutil.which(first) or os.path.isfile(first):
            return configured
        return None
    return shutil.which("nextpnr-generic")


def _skip_reason():
    if os.environ.get(OPTION) != "1":
        return ("from-source route-invariance is opt-in: set %s=1 to run it "
                "(a real synth+route build, minutes per design)" % OPTION)
    if not _tool("yosys"):
        return "open-flow tools absent (need yosys on PATH or $AGAMEMNON_OSS/bin)"
    if not _uarch_nextpnr():
        return ("agrv2k uarch nextpnr-generic absent (need $AGAMEMNON_UARCH_NEXTPNR "
                "or nextpnr-generic on PATH built via "
                "agamemnon/engine/uarch/agrv2k/build.sh)")
    return None


def _design_ids():
    return [design["id"] for design in REGISTRY["designs"]]


def test_registry_is_well_formed():
    assert REGISTRY["schema"] == "agamemnon.route-from-source-regression.v1"
    assert REGISTRY["hash_mode"] == "routed-sha256-lf-v1"
    assert isinstance(REGISTRY["description"], str) and REGISTRY["description"]
    designs = REGISTRY["designs"]
    assert designs, "the from-source route registry must name at least one design"
    ids = [design["id"] for design in designs]
    assert len(ids) == len(set(ids)), "duplicate design id in the registry"
    for design in designs:
        fields = {
            "id", "source", "source_sha256", "build_args", "build_environment",
            "route_sha256", "pinned_date", "reason", "known_open_defect_reference",
        }
        assert set(design) == fields, "registry entry field set mismatch: %r" % design
        assert design["reason"].strip(), "every pin needs a non-empty reason: %r" % design["id"]
        assert (ROOT / design["source"]).is_file(), \
            "registered source is missing: %s" % design["source"]


@pytest.mark.parametrize("design", REGISTRY["designs"], ids=_design_ids())
def test_registered_source_matches_its_pinned_hash(design):
    """Cheap, toolchain-free: catches a silently-edited source file on its own,
    never masked by the (possibly xfail'd) build-and-route check below."""
    source = ROOT / design["source"]
    assert _sha256_bytes(source) == design["source_sha256"], (
        "%s changed since its route hash was pinned in %s. A source edit can "
        "legitimately change the route; re-derive and record a fresh "
        "source_sha256 AND route_sha256 together, with a dated reason -- "
        "never update one without the other."
        % (design["source"], REGISTRY_PATH.relative_to(ROOT).as_posix())
    )


def _from_source_params():
    params = []
    for design in REGISTRY["designs"]:
        marks = []
        reference = design.get("known_open_defect_reference")
        if reference:
            marks.append(pytest.mark.xfail(
                reason="known open regression, not this mechanism's bug: %s" % reference,
                strict=False,
            ))
        params.append(pytest.param(design, marks=marks, id=design["id"]))
    return params


@pytest.mark.parametrize("design", _from_source_params())
def test_from_source_route_matches_pin(design, tmp_path):
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    source = ROOT / design["source"]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("AGAMEMNON_") or key in _TOOL_LOCATION_VARS}
    env.update(design["build_environment"])
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])

    routed_out = tmp_path / (design["id"] + "_routed.json")
    bin_out = tmp_path / (design["id"] + ".bin")
    cmd = [
        sys.executable, "-m", "agamemnon.cli", "build", str(source),
        *design["build_args"],
        "--write-routed", str(routed_out),
        "-o", str(bin_out),
    ]
    result = subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, (
        "from-source rebuild of %s could not complete -- treated as a route-"
        "invariance FAILURE, not a skip (absence of the ability to verify is "
        "not a pass):\n%s" % (design["id"], result.stdout[-3000:] + result.stderr[-3000:])
    )
    assert routed_out.is_file(), "build reported success but wrote no routed JSON"

    actual_route_sha256 = _sha256_text(routed_out)
    assert actual_route_sha256 == design["route_sha256"], (
        "from-source route-invariance regression: a fresh synth+place+route of "
        "%s no longer reaches the pinned route.\n"
        "  expected route sha256: %s\n"
        "  actual   route sha256: %s\n"
        "  actual bitstream sha256: %s\n"
        "This means nextpnr chose a DIFFERENT route for unchanged source under "
        "the currently installed chipdb -- exactly the 2026-08-18 failure mode "
        "this check exists to catch. Do not re-pin route_sha256 in %s without "
        "independently re-verifying the new route (board re-read or an "
        "equivalent documented desk audit) and recording why the new route is "
        "trustworthy; see that file's own re-baselining rule."
        % (design["id"], design["route_sha256"], actual_route_sha256,
           _sha256_bytes(bin_out) if bin_out.is_file() else "<no .bin produced>",
           REGISTRY_PATH.relative_to(ROOT).as_posix())
    )
