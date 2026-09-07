"""Pytest configuration for the AGaMEMnon test suite.

Exposes the bundled real-silicon fixture path. The whole suite is self-contained:
no external data files and no hardware.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from agamemnon.engine import routing_admission

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BLINKY_BIN = os.path.join(FIXTURES, "blinky.bin")


@pytest.fixture
def blinky_bin_path():
    """Absolute path to the 2921-byte real fabric .bin fixture (cpld_native/blinky.bin)."""
    assert os.path.exists(BLINKY_BIN), f"missing fixture: {BLINKY_BIN}"
    return BLINKY_BIN


@pytest.fixture
def blinky_bin_bytes(blinky_bin_path):
    """Raw bytes of the fixture .bin."""
    with open(blinky_bin_path, "rb") as f:
        return f.read()


# --------------------------------------------------------------------------- #
# GAP-1 process-hole closure (AG32-Docs docs/TASK_QUEUE.md queue B task B3).
#
# Background: agamemnon.engine.routing_admission._real_route_invariance_check
# ("D0 Rule 2") rebuilds every retained qualified artifact and rejects a
# candidate promotion that changes one -- but it only ever runs when a D0
# default-promotion approval artifact (agamemnon/chipdb/d0_default_promotion_
# approval.json) is present and read. A hand edit to any OTHER file under
# agamemnon/chipdb/ -- e.g. a plain CSV row addition, committed directly --
# never goes through that path at all. That is exactly what happened on
# 2026-08-18: one added CSV row silently changed the packed bytes of seven
# silicon-qualified artifacts, and only a byte-identity test
# (tests/test_qualified_pack_regression.py) caught it -- days later, because
# nothing forced that test to run the moment the chipdb changed.
#
# The fixture below closes that trigger-coverage gap: it fires for every
# pytest session that touches this tests/ directory tree AT ALL, regardless
# of which specific test file(s) are named on the command line (conftest.py
# is loaded for the whole directory by pytest's own collection machinery, so
# `pytest tests/test_d0_default_promotion.py` alone still loads and runs it --
# unlike a standalone test_*.py file, which only executes when that exact
# file is collected). It cannot be skipped by picking a narrow test target;
# it can only be skipped by not running pytest against this tree at all,
# which is a much smaller and more visible hole than "remember to run the
# right test file."
#
# What this DOES cover: any byte of any file physically present under
# agamemnon/chipdb/, whenever pytest runs. On a cheap fingerprint mismatch it
# escalates to calling Rule 2 itself --
# routing_admission.rebuild_retained_qualified_artifacts, a thin public
# wrapper added specifically for this -- against the CURRENT chipdb,
# unconditional of D0 approval state. That is the same rebuild-and-compare
# tests/test_qualified_pack_regression.py performs per-artifact, reused
# rather than re-implemented so there is exactly one fail-closed
# rebuild-and-compare code path, not two that could quietly diverge.
#
# What this does NOT cover: engine code changes (bitgen.py, features/
# routing.py, default_frame.py, ...) -- those are ordinary source, reviewed
# and tested like any other code change, not a "data" surface this tripwire
# watches. It does NOT cover route drift on a fresh synth+place+route (a
# repack-neutral chipdb change can still make nextpnr pick a different route
# from source -- see tests/test_route_from_source_invariance.py, which is
# the from-source counterpart and is opt-in because it needs a real
# yosys+nextpnr build). And it is not magic: if nobody ever runs pytest
# against a changed working tree, this cannot fire -- CI already runs the
# full suite on every push/PR (.github/workflows/ci.yml), which is the actual
# backstop for that case; this fixture's job is to make sure a LOCAL, narrow,
# selective test run cannot quietly miss the same signal.
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
CHIPDB_ROOT = ROOT / "agamemnon" / "chipdb"
CHIPDB_FINGERPRINT_PIN_PATH = Path(FIXTURES) / "chipdb_fingerprint_pin.json"


def compute_chipdb_fingerprint(root=CHIPDB_ROOT):
    """Deterministic content fingerprint over every file under agamemnon/chipdb/.

    Sorted by relative POSIX path so the result is independent of directory
    listing order; each file contributes its path and its own SHA-256, so a
    rename and a content edit are both detected (and distinguished from each
    other, since the file count and the set of paths hashed both change).
    Returns (fingerprint_hex, file_count).

    The sort key is deliberately an explicit, case-folded string comparison
    on the relative POSIX path (tie-broken by the exact-case path), NOT bare
    ``sorted(Path, ...)``: ``pathlib.WindowsPath.__lt__`` compares
    case-folded (``os.path.normcase``) strings, while ``pathlib.PosixPath``
    (WSL/Linux) compares raw, case-sensitive strings. Sorting bare Path
    objects therefore silently reorders any two entries whose relative
    case-insensitive order differs from their case-sensitive order, which
    changes this running/incremental digest even though the exact same set
    of (path, content) pairs is hashed -- an OS-dependent false positive,
    not a real chipdb content change. This exact drift produced a fingerprint
    pinned on a Windows checkout that a WSL/Linux checkout of the identical
    tree could never reproduce (tests/fixtures/chipdb_fingerprint_pin.json's
    2026-08-18 pin). The case-folded key reproduces the historical
    Windows-native traversal order on every platform, so this fix requires
    no pin update.
    """
    root_path = Path(root)

    def _sort_key(path):
        rel = path.relative_to(root_path).as_posix()
        return (rel.casefold(), rel)

    files = sorted((p for p in root_path.rglob("*") if p.is_file()), key=_sort_key)
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root_path).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest(), len(files)


def load_chipdb_fingerprint_pin():
    return json.loads(CHIPDB_FINGERPRINT_PIN_PATH.read_text(encoding="utf-8"))


def _rebuild_retained_corpus_failure():
    """Escalation path: run Rule 2 itself
    (``routing_admission.rebuild_retained_qualified_artifacts``) against the
    CURRENT chipdb. Returns None if every retained artifact rebuilds
    byte-identical, else the exact :class:`RoutingAdmissionError` message.

    Deliberately calls the real Rule 2 implementation rather than a parallel
    reimplementation of "re-pack and compare": that is the literal fix for
    GAP 1 (Rule 2 gated on a D0 approval read that a bare chipdb edit never
    produces) -- reusing the one reviewed, fail-closed implementation instead
    of maintaining a second copy that could quietly drift from it.
    """
    try:
        routing_admission.rebuild_retained_qualified_artifacts(CHIPDB_ROOT)
    except routing_admission.RoutingAdmissionError as exc:
        return str(exc)
    return None


def chipdb_change_gate_failure():
    """None if agamemnon/chipdb/ matches its recorded pin; otherwise a full,
    actionable failure message.

    Escalates to Rule 2's real rebuild-and-compare of the entire retained
    corpus (~58 artifacts) ONLY when the cheap fingerprint check first
    detects a change -- an unchanged chipdb costs one sub-second directory
    hash per pytest session; a changed chipdb costs the expensive
    verification exactly when that cost is actually warranted. Rule 2 stops
    at the first mismatch or first unrebuildable artifact (its own
    documented fail-closed contract), so only one failure is ever reported
    here, not an exhaustive list.
    """
    pin = load_chipdb_fingerprint_pin()
    fingerprint, file_count = compute_chipdb_fingerprint()
    if fingerprint == pin["fingerprint_sha256"] and file_count == pin["file_count"]:
        return None

    rule2_failure = _rebuild_retained_corpus_failure()
    lines = [
        "agamemnon/chipdb/ content changed: live fingerprint %s (%d files) != "
        "pinned %s (%d files) recorded in tests/fixtures/chipdb_fingerprint_pin.json "
        "(pinned %s: %s)."
        % (fingerprint, file_count, pin["fingerprint_sha256"], pin["file_count"],
           pin.get("pinned_date"), pin.get("reason")),
        "",
        "This is the GAP-1 tripwire (AG32-Docs docs/TASK_QUEUE.md queue B task "
        "B3): ANY chipdb content change -- not only a D0 default-promotion "
        "approval read -- must be caught here, in every pytest session, "
        "regardless of which test file(s) were selected on the command line. "
        "It just ran D0 Rule 2 (routing_admission.rebuild_retained_qualified_"
        "artifacts) against the current chipdb on your behalf.",
        "",
    ]
    if rule2_failure is not None:
        lines.append("Rule 2 rejected the current chipdb:")
        lines.append("  " + rule2_failure)
        lines.append(
            "This is a real regression. Fix or revert the chipdb change; do "
            "not update the pin to paper over a Rule 2 rejection."
        )
    else:
        lines.append(
            "Rule 2 found every included release-strict-relevant retained artifact still "
            "rebuilds byte-identical to its pinned hash. That proves the "
            "change is repack-neutral for the included pinned subset; research-policy "
            "artifacts are excluded and require the full qualified-pack tests. It does "
            "NOT prove the change is correct, and it says nothing about "
            "route-invariance for a fresh synth+place+route (see "
            "tests/test_route_from_source_invariance.py: a repack-neutral "
            "chipdb change can still make nextpnr choose a different, wrong "
            "route from source -- that is exactly the 2026-08-18 incident)."
        )
    lines.append(
        "If this change is deliberate and reviewed, update "
        "tests/fixtures/chipdb_fingerprint_pin.json with the new "
        "fingerprint_sha256/file_count (see compute_chipdb_fingerprint in this "
        "file) AND a dated, specific 'reason' -- never regenerate that file "
        "mechanically without answering the above."
    )
    return "\n".join(lines)


@pytest.fixture(scope="session")
def chipdb_fingerprint_pin():
    """The recorded pin, loaded once per session; used by
    tests/test_chipdb_fingerprint_gate.py to check the pin's own structure
    (non-empty reason, valid date, valid hash) independent of whether it
    currently matches the live chipdb."""
    return load_chipdb_fingerprint_pin()


@pytest.fixture(scope="session")
def chipdb_change_gate_message():
    """Session-cached result of chipdb_change_gate_failure(): computed once
    per pytest session no matter how many tests or files need it (the
    autouse enforcement fixture below and
    tests/test_chipdb_fingerprint_gate.py's discoverable, individually-
    runnable copy both depend on this exact fixture rather than recomputing)."""
    return chipdb_change_gate_failure()


@pytest.fixture(scope="session", autouse=True)
def _chipdb_change_gate(chipdb_change_gate_message):
    """Autouse, session-scoped: every test in this directory tree implicitly
    depends on this fixture, so it runs before the first test of any pytest
    invocation that collects anything here -- see the module-level banner
    above for the full contract (what this does and does not cover)."""
    assert chipdb_change_gate_message is None, chipdb_change_gate_message


@pytest.fixture(scope="session", autouse=True)
def _generated_test_databases(_chipdb_change_gate):
    """Prepare profiles requested by collected tests after the data gate passes."""
    from devdb_fixtures import DATABASES
    DATABASES.prepare()
    yield
    DATABASES.close()
