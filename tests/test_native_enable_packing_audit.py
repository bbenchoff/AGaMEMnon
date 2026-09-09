"""Placed-native-enable packing audit helper tests."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_enable_packing_audit", ROOT / "tools" / "analyze_native_enable_packing.py",
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _slice(*, bel, ff_used, enable=None):
    attrs = {"NEXTPNR_BEL": bel}
    if enable:
        attrs["AGRV2K_CLOCK_ENABLE_NET"] = enable
    return {"type": "GENERIC_SLICE", "attributes": attrs,
            "parameters": {"FF_USED": str(int(ff_used))}}


def _control(*, bel, enable):
    return {"type": "AGRV2K_TILE_CONTROL",
            "attributes": {"NEXTPNR_BEL": bel,
                           "AGRV2K_CLOCK_ENABLE_NET": enable},
            "parameters": {}}


def _document(cells):
    return {"modules": {"top": {"cells": cells}}}


def test_same_enable_coalesces_and_leaves_combinational_capacity():
    cells = {"control": _control(bel="X17Y10_CLKEN0", enable="write_en")}
    for index in range(8):
        cells["native%d" % index] = _slice(
            bel="X17Y10_SLICE%d" % index, ff_used=True, enable="write_en",
        )
    for index in range(8, 12):
        cells["lut%d" % index] = _slice(
            bel="X17Y10_SLICE%d" % index, ff_used=False,
        )
    report = AUDIT.analyze(_document(cells))
    assert report["valid"], report["errors"]
    assert report["groups"] == [{
        "enable": "write_en", "native_ffs": 8, "tiles": 1,
        "expected_tiles": 1, "member_tiles": {"X17Y10": 8},
    }]
    assert report["tiles"] == [{
        "tile": "X17Y10", "native_ffs": 8,
        "combinational_slices": 4, "free_slices": 4,
    }]


def test_a_native_tile_rejects_ordinary_ff_and_excess_root_fragmentation():
    cells = {
        "root0": _control(bel="X17Y10_CLKEN0", enable="write_en"),
        "root1": _control(bel="X17Y11_CLKEN0", enable="write_en"),
        "native": _slice(bel="X17Y10_SLICE0", ff_used=True, enable="write_en"),
        "ordinary": _slice(bel="X17Y10_SLICE1", ff_used=True),
    }
    report = AUDIT.analyze(_document(cells))
    assert not report["valid"]
    assert any("ordinary FFs" in error for error in report["errors"])
    assert any("empty control-root tiles" in error for error in report["errors"])
    assert any("uses 2 roots for 1 FFs; expected 1" in error for error in report["errors"])


def test_a_group_above_sixteen_requires_exactly_two_control_tiles():
    cells = {}
    for tile in ("X17Y10", "X17Y11"):
        cells["control_" + tile] = _control(bel=tile + "_CLKEN0", enable="write_en")
    for index in range(17):
        tile, slot = ("X17Y10", index) if index < 16 else ("X17Y11", 0)
        cells["native%d" % index] = _slice(
            bel=tile + "_SLICE%d" % slot, ff_used=True, enable="write_en",
        )
    report = AUDIT.analyze(_document(cells))
    assert report["valid"], report["errors"]
    assert report["groups"][0]["expected_tiles"] == 2


def test_different_enable_groups_cannot_share_a_tile():
    cells = {}
    for index, enable in enumerate(('a', 'b')):
        cells['root' + enable] = _control(bel='X17Y10_CLKEN0', enable=enable)
        cells['ff' + enable] = _slice(
            bel='X17Y10_SLICE%d' % index, ff_used=True, enable=enable)
    report = AUDIT.analyze(_document(cells))
    assert not report['valid']
    assert any('different enable groups' in error for error in report['errors'])


def test_missing_placement_is_not_silently_ignored():
    report = AUDIT.analyze(_document({
        'ff': _slice(bel=None, ff_used=True, enable='a'),
        'root': _control(bel='X17Y10_CLKEN0', enable='a'),
    }))
    assert not report['valid']
    assert any('lacks a placed' in error for error in report['errors'])
    assert any('no native members' in error for error in report['errors'])
