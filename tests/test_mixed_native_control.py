"""Compiled boundary for one native-enable group plus ordinary state."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import test_uarch_register_input_legality as support


TILE = "X14Y8"


def _native_slice(name, enable, z):
    cell = support._generic(
        "LUT_FEEDTHROUGH_I0", init=0xAAAA, inputs=(0,),
        bel="%s_SLICE%d" % (TILE, z), base=100 + z * 20,
    )
    cell["attributes"].update({
        "AGRV2K_SHARED_CONTROL_MODE": "CLOCK_ENABLE_POS",
        "AGRV2K_CLOCK_ENABLE_NET": enable,
    })
    return cell


def _ordinary_slice(z):
    return support._generic(
        "LUT_FEEDTHROUGH_I0", init=0xAAAA, inputs=(0,),
        bel="%s_SLICE%d" % (TILE, z), base=1000 + z * 20,
    )


def _control(enable, line):
    return {
        "hide_name": 0, "type": "AGRV2K_TILE_CONTROL", "parameters": {},
        "attributes": {
            "NEXTPNR_BEL": "%s_CLKEN%d" % (TILE, line),
            "BEL_STRENGTH": format(5, "032b"),
            "AGRV2K_CLOCK_ENABLE_NET": enable,
        },
        "port_directions": {"I": "input"},
        "connections": {"I": [30 + line]},
    }


def _design(root_groups=("enable_a",), native_groups=None, ordinary=True):
    if native_groups is None:
        native_groups = root_groups
    cells = {}
    netnames = {}
    for line, enable in enumerate(root_groups):
        cells["root_%d" % line] = _control(enable, line)
        netnames.setdefault(enable, 30 + line)
    for z, enable in enumerate(native_groups):
        cells["native_%d" % z] = _native_slice("native_%d" % z, enable, z)
        netnames.setdefault(enable, 50 + z)
    if ordinary:
        cells["ordinary"] = _ordinary_slice(len(native_groups) + 1)
    return support._design(cells, netnames)


def _run(tmp_path, monkeypatch, name, groups, mixed, *, native_groups=None, ordinary=True):
    if os.environ.get("AGAMEMNON_UARCH_DEVDB"):
        monkeypatch.setattr(support, "DEVDB", Path(os.environ["AGAMEMNON_UARCH_DEVDB"]))
    monkeypatch.setenv("AGRV2K_SHARED_CONTROL_ENABLE", "1")
    monkeypatch.setenv("AGRV2K_DUAL_NATIVE_CONTROL", "1")
    monkeypatch.setenv("AGRV2K_MIXED_NATIVE_CONTROL", mixed)
    return support._run(
        tmp_path, name, _design(groups, native_groups, ordinary), "--no-pack", "--no-route", "--placer", "heap",
    )


def test_mixed_native_control_is_off_by_default(tmp_path, monkeypatch):
    result, log, _ = _run(tmp_path, monkeypatch, "mixed_off", ("enable_a",), "0")
    assert result.returncode != 0
    assert "AGRV2K_MIXED_NATIVE_CONTROL=1" in log


def test_mixed_native_control_allows_one_group_and_ordinary_state(tmp_path, monkeypatch):
    result, log, output = _run(tmp_path, monkeypatch, "mixed_on", ("enable_a",), "1")
    assert result.returncode == 0, log
    assert output.exists()


@pytest.mark.parametrize("groups", [("enable_a", "enable_b"), ("enable_b", "enable_a")])
def test_mixed_native_control_rejects_two_native_groups_symmetrically(
        tmp_path, monkeypatch, groups):
    result, log, _ = _run(tmp_path, monkeypatch, "two_" + groups[0], groups, "1")
    assert result.returncode != 0
    assert "exactly one native enable group" in log


@pytest.mark.parametrize("value", ("", "yes", "2", "-1"))
def test_mixed_native_control_rejects_non_boolean_switch(tmp_path, monkeypatch, value):
    result, log, _ = _run(tmp_path, monkeypatch, "bad_" + (value or "empty"),
                          ("enable_a",), value)
    assert result.returncode != 0
    assert "AGRV2K_MIXED_NATIVE_CONTROL must be exactly 0 or 1" in log


@pytest.mark.parametrize("mixed", ("0", "1"))
def test_native_only_rejects_unmatched_enable_group(tmp_path, monkeypatch, mixed):
    result, log, _ = _run(tmp_path, monkeypatch, "unmatched_" + mixed,
                          ("enable_a",), mixed, native_groups=("enable_b",), ordinary=False)
    assert result.returncode != 0
    assert "control-group mismatch" in log


@pytest.mark.parametrize("mixed", ("0", "1"))
def test_mixed_control_rejects_two_occupied_lines_with_same_group(tmp_path, monkeypatch, mixed):
    result, log, _ = _run(tmp_path, monkeypatch, "duplicate_roots_" + mixed,
                          ("enable_a", "enable_a"), mixed)
    assert result.returncode != 0
    if mixed == "0":
        assert "AGRV2K_MIXED_NATIVE_CONTROL=1" in log
    else:
        assert "reserves the other local clock line" in log


@pytest.mark.parametrize("mixed", ("0", "1"))
def test_ordinary_only_register_tile_remains_legal(tmp_path, monkeypatch, mixed):
    result, log, output = _run(tmp_path, monkeypatch, "ordinary_only_" + mixed,
                               (), mixed, ordinary=True)
    assert result.returncode == 0, log
    assert output.exists()


@pytest.mark.parametrize("mixed", ("0", "1"))
def test_native_only_register_tile_preserves_legacy_legality(tmp_path, monkeypatch, mixed):
    result, log, output = _run(tmp_path, monkeypatch, "native_only_" + mixed,
                               ("enable_a",), mixed, ordinary=False)
    assert result.returncode == 0, log
    assert output.exists()
