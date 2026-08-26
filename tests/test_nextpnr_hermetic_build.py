"""Release-integrity checks for the pinned nextpnr overlay build."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k"


def test_build_applies_every_required_nextpnr_patch_and_probe_overlay():
    build = (UARCH / "build.sh").read_text(encoding="utf-8")
    assert 'apply_nextpnr_patch "$HERE/nextpnr-viaduct-timing.patch"' in build
    assert 'apply_nextpnr_patch "$HERE/nextpnr-router2-reservations.patch"' in build
    assert "router2_probe_uarch/constids.inc" in build
    assert "router2_probe_uarch/router2_probe.cc" in build
    assert "viaduct/agamemnon_router2_probe/router2_probe.cc" in build
    assert '[ ! -e "$NEXTPNR/.git" ]' in build  # normal clones and linked worktrees


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


def test_dead_router2_stagnation_environment_setting_is_gone():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert "NEXTPNR_ROUTER2_STAGNATION_LIMIT" not in cli


def test_probe_uarch_is_synthetic_and_contains_no_device_coordinates():
    source = (UARCH / "router2_probe_uarch" / "router2_probe.cc").read_text(encoding="utf-8")
    assert 'ViaductArch("agamemnon_router2_probe")' in source
    assert "LOCAL_GND" in source and "CHOKE" in source
    assert re.search(r"\bX\d+Y\d+\b", source) is None
