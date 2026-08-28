"""Compiled closure tests for the bounded N5.7A single-GCLK0 model."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEVDB = (
    ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
)


def _tool():
    path = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not path or not Path(path).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    return path


def _devdb():
    path = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", DEFAULT_DEVDB))
    if not path.is_dir():
        pytest.skip("set AGAMEMNON_UARCH_DEVDB to the matching generated devdb")
    return path


def _source(kind, bit, *, fixed_hse=False):
    hse = kind == "GENERIC_IOB"
    attributes = {}
    if fixed_hse:
        attributes = {
            "NEXTPNR_BEL": "CLKIN",
            "BEL_STRENGTH": "00000000000000000000000000000101",
        }
    port = "O" if hse else "CLK"
    return {
        "hide_name": 0,
        "type": kind,
        "parameters": {},
        "attributes": attributes,
        "port_directions": {port: "output"},
        "connections": {port: [bit]},
    }


def _slice(clock, output, bel, *, active=True):
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(int(active), "032b"),
            "INIT": "0000000000000000",
            "K": format(4, "032b"),
        },
        "attributes": {
            "AGRV2K_REGISTER_INPUT_MODE": (
                "LUT_COMPUTE_TO_FF" if active else "NONE"
            ),
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": "00000000000000000000000000000101",
        },
        "port_directions": {
            "Q": "output", "F": "output", "CLK": "input", "I": "input",
        },
        "connections": {
            "Q": [output] if active else [],
            "F": [] if active else [output],
            "CLK": [clock],
            "I": ["x", "x", "x", "x"],
        },
    }


def _bram(clock):
    return {
        "hide_name": 0,
        "type": "ALTA_BRAM9K",
        "parameters": {},
        "attributes": {
            "NEXTPNR_BEL": "X13Y4_BRAM",
            "BEL_STRENGTH": "00000000000000000000000000000101",
        },
        "port_directions": {"Clk0": "input"},
        "connections": {"Clk0": [clock]},
    }


def _netlist(cells, nets):
    return {
        "creator": "N5.7A compiled typed-clock test",
        "modules": {
            "top": {
                "attributes": {"top": 1},
                "ports": {},
                "cells": cells,
                "netnames": {
                    name: {"hide_name": 0, "bits": [bit], "attributes": {}}
                    for name, bit in nets.items()
                },
            }
        },
    }


def _run(tmp_path, name, document, *flags):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=" + str(_devdb()),
         "--json", str(source), "--write", str(output), *flags],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, output


def _one_ff(source_kind="MCU_BUS_CLOCK", *, fixed_hse=False):
    return _netlist(
        {
            "clock_source": _source(source_kind, 2, fixed_hse=fixed_hse),
            "state": _slice(2, 20, "X1Y1_SLICE0"),
        },
        {"clock": 2, "q": 20},
    )


@pytest.mark.parametrize("source_kind", ["MCU_BUS_CLOCK", "GENERIC_IOB"])
def test_admitted_sources_lock_one_exact_tree(source_kind, tmp_path):
    result, output = _run(
        tmp_path, source_kind, _one_ff(source_kind), "--router", "router2"
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "loaded typed GCLK0 authority" in log
    expected_pips = 2 if source_kind == "GENERIC_IOB" else 1
    assert "atomically bound %d typed GCLK0 tree PIP(s)" % expected_pips in log
    packed = json.loads(output.read_text(encoding="utf-8"))
    route = packed["modules"]["top"]["netnames"]["clock"]["attributes"]["ROUTING"]
    assert "GCLK0.X1Y1_ClkMUX00" in route
    if source_kind == "GENERIC_IOB":
        assert "X14Y13_InputMUX01.GCLK0" in route


def test_inactive_slice_clock_is_canonicalized_before_tree_closure(tmp_path):
    document = _one_ff()
    module = document["modules"]["top"]
    module["cells"]["inactive_logic"] = _slice(
        2, 21, "X1Y1_SLICE2", active=False
    )
    module["netnames"]["f"] = {"hide_name": 0, "bits": [21], "attributes": {}}
    result, output = _run(tmp_path, "inactive", document, "--pack-only")
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "canonicalized 1 inactive slice clock connection(s)" in log
    packed = json.loads(output.read_text(encoding="utf-8"))
    assert packed["modules"]["top"]["cells"]["inactive_logic"][
        "connections"
    ]["CLK"] == []


def test_single_connected_bram_port_uses_the_exact_three_hop_tree(tmp_path):
    document = _netlist(
        {"clock_source": _source("MCU_BUS_CLOCK", 2), "memory": _bram(2)},
        {"clock": 2},
    )
    result, output = _run(tmp_path, "bram", document, "--router", "router2")
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "atomically bound 3 typed GCLK0 tree PIP(s)" in log
    route = json.loads(output.read_text(encoding="utf-8"))[
        "modules"
    ]["top"]["netnames"]["clock"]["attributes"]["ROUTING"]
    for token in (
        "GCLK0.X13Y0_BufMUX05",
        "X13Y0_BufMUX05.X13Y4_SeamMUX01",
        "X13Y4_SeamMUX01.X13Y4_TileClkMUX01",
    ):
        assert token in route


@pytest.mark.parametrize(
    ("document", "diagnostic"),
    [
        (_one_ff("MCU_SYS_CLOCK"), "rejects unsupported source class MCU_SYS"),
        (
            _netlist(
                {
                    "bus_source": _source("MCU_BUS_CLOCK", 2),
                    "hse_source": _source("GENERIC_IOB", 3, fixed_hse=True),
                    "state_a": _slice(2, 20, "X1Y1_SLICE0"),
                    "state_b": _slice(3, 21, "X2Y1_SLICE0"),
                },
                {"clock_a": 2, "clock_b": 3, "q_a": 20, "q_b": 21},
            ),
            "rejects multiple whole-device clocks",
        ),
    ],
)
def test_unsupported_or_multiple_sources_fail_closed(document, diagnostic, tmp_path):
    result, output = _run(tmp_path, "source_negative", document, "--pack-only")
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr
    assert not output.exists()


def _complete_hse_route(tmp_path):
    result, output = _run(
        tmp_path, "complete_hse", _one_ff("GENERIC_IOB"), "--router", "router2"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def test_complete_no_pack_no_place_reimport_passes(tmp_path):
    routed = _complete_hse_route(tmp_path)
    result, output = _run(
        tmp_path, "reimport", routed, "--no-pack", "--no-place",
        "--router", "router2",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.is_file()


@pytest.mark.parametrize(
    ("route", "diagnostic"),
    [
        (
            "X14Y13_InputMUX01;;1;GCLK0;X14Y13_InputMUX01.GCLK0;5",
            "partial imported tree",
        ),
        (
            "X14Y13_InputMUX01;;1;X1Y1_ClkMUX00;GCLK0.X1Y1_ClkMUX00;5;"
            "X1Y1_ClkMUX01;GCLK0.X1Y1_ClkMUX01;5;"
            "GCLK0;X14Y13_InputMUX01.GCLK0;5",
            "rejects extra/foreign/wrong-class PIP",
        ),
    ],
)
def test_partial_or_extra_imported_tree_fails_closed(route, diagnostic, tmp_path):
    routed = _complete_hse_route(tmp_path)
    changed = copy.deepcopy(routed)
    changed["modules"]["top"]["netnames"]["clock"]["attributes"]["ROUTING"] = route
    result, output = _run(
        tmp_path, "bad_import", changed, "--no-pack", "--no-place",
        "--router", "router2",
    )
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr
    assert not output.exists()
