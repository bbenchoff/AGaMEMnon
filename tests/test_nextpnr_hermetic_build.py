"""Release-integrity checks for the pinned nextpnr overlay build."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k"


def test_build_applies_every_required_nextpnr_patch_and_probe_overlay():
    build = (UARCH / "build.sh").read_text(encoding="utf-8")
    assert 'apply_nextpnr_patch "$HERE/nextpnr-viaduct-timing.patch"' in build
    assert 'apply_nextpnr_patch "$HERE/nextpnr-viaduct-clusters.patch"' in build
    assert 'apply_nextpnr_patch "$HERE/nextpnr-router2-reservations.patch"' in build
    assert "router2_probe_uarch/constids.inc" in build
    assert "router2_probe_uarch/router2_probe.cc" in build
    assert "viaduct/agamemnon_router2_probe/router2_probe.cc" in build
    assert '[ ! -e "$NEXTPNR/.git" ]' in build  # normal clones and linked worktrees
    # The compiled legality implementation must be the reviewed overlay byte
    # source, never a separately maintained copy in nextpnr.
    assert 'cp "$HERE/agrv2k.cc" "$DEST/agrv2k.cc"' in build
    assert 'echo "-- overlaid agrv2k.cc -> $DEST"' in build
    assert "verify_uarch_registration" in build
    assert "--verify-uarch-registration" in build
    assert '[ "$status" -ne 125 ]' in build
    assert "available[[:space:]]options" in build


def test_router_patch_contains_both_reservation_safeguards():
    patch = (UARCH / "nextpnr-router2-reservations.patch").read_text(encoding="utf-8")
    assert 'ctx->id("$PACKER_GND_NET")' in patch
    assert 'ctx->id("$PACKER_VCC_NET")' in patch
    assert "reservation_blocked" in patch
    assert "leaving it unreserved for ordinary" in patch


def test_viaduct_patch_exposes_timing_and_local_constant_sources():
    patch = (UARCH / "nextpnr-viaduct-timing.patch").read_text(encoding="utf-8")
    assert "uarch->getWireDelay(wire, delay)" in patch
    assert "uarch->getPipDelay(pip, delay)" in patch
    assert "uarch->getWireConstantValue(wire)" in patch


def test_viaduct_cluster_patch_delegates_to_the_uarch_only_when_claimed():
    patch = (UARCH / "nextpnr-viaduct-clusters.patch").read_text(encoding="utf-8")
    assert "virtual bool handlesClusterPlacement(ClusterId" in patch
    assert "virtual bool getClusterPlacement(ClusterId" in patch
    assert "uarch && uarch->handlesClusterPlacement(cluster)" in patch
    assert "return uarch->getClusterPlacement(cluster, root_bel, placement);" in patch
    assert "return BaseArch<ArchRanges>::getClusterPlacement(cluster, root_bel, placement);" in patch


def test_dead_router2_stagnation_environment_setting_is_gone():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert "NEXTPNR_ROUTER2_STAGNATION_LIMIT" not in cli


def test_probe_uarch_is_synthetic_and_contains_no_device_coordinates():
    source = (UARCH / "router2_probe_uarch" / "router2_probe.cc").read_text(encoding="utf-8")
    assert 'ViaductArch("agamemnon_router2_probe")' in source
    assert "LOCAL_GND" in source and "CHOKE" in source
    assert re.search(r"\bX\d+Y\d+\b", source) is None



@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="this shell-level test runs in POSIX CI")
@pytest.mark.parametrize(
    ("name", "exit_code", "line", "expected"),
    [
        (
            "registered",
            125,
            "ERROR: Unknown viaduct uarch '?', available options: 'fabulous, agrv2k, agamemnon_router2_probe, example'",
            True,
        ),
        (
            "missing",
            125,
            "ERROR: Unknown viaduct uarch '?', available options: 'fabulous, example'",
            False,
        ),
        (
            "wrong-status",
            1,
            "ERROR: Unknown viaduct uarch '?', available options: 'fabulous, agrv2k, example'",
            False,
        ),
    ],
)
def test_uarch_registration_probe_requires_expected_sentinel_and_exact_enumeration(
    tmp_path, name, exit_code, line, expected
):
    stub = tmp_path / f"nextpnr-{name}.sh"
    stub.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"{line}\" >&2\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(UARCH / "build.sh"), "--verify-uarch-registration", str(stub)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert (completed.returncode == 0) is expected
    if expected:
        assert "verified agrv2k uarch registration" in completed.stdout
    else:
        assert "verified agrv2k uarch registration" not in completed.stdout
