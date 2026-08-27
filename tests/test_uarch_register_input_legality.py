"""Compiled AGRV2K register-input packing and hard legality boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEVDB = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"


def _tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    if not (DEVDB / "dev_pips.csv").is_file():
        pytest.skip("emit the strict agrv2k devdb before register-input tests")
    return executable


def _raw_dff(name, clock, data, q, bel=None):
    attrs = {}
    if bel:
        attrs = {"NEXTPNR_BEL": bel, "BEL_STRENGTH": format(5, "032b")}
    return {
        "hide_name": 0,
        "type": "DFF",
        "parameters": {},
        "attributes": attrs,
        "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
        "connections": {"CLK": [clock], "D": [data], "Q": [q]},
    }


def _lut(name, init, inputs, output, tags=()):
    attrs = {tag: "1" for tag in tags}
    return {
        "hide_name": 0, "type": "LUT",
        "parameters": {"INIT": format(init, "016b"), "K": format(4, "032b")},
        "attributes": attrs,
        "port_directions": {"I": "input", "Q": "output"},
        "connections": {"I": list(inputs), "Q": [output]},
    }


def _generic(mode, *, init=0, inputs=(), bel="X14Y8_SLICE0", tags=(),
             f_used=False, carry=False, own_q_i3=False):
    q, clk, f = 20, 2, 30
    i = [100 + index for index in range(4)]
    if own_q_i3:
        i[3] = q
        inputs = tuple(set(inputs) | {3})
    connections = {
        "Q": [q], "CLK": [clk], "F": [f] if f_used else [],
        "I": [i[index] if index in inputs else "x" for index in range(4)],
    }
    directions = {"Q": "output", "CLK": "input", "F": "output", "I": "input"}
    if carry:
        connections.update({"CIN": [40], "COUT": [41]})
        directions.update({"CIN": "input", "COUT": "output"})
    attrs = {
        "NEXTPNR_BEL": bel,
        "BEL_STRENGTH": format(5, "032b"),
        "AGRV2K_REGISTER_INPUT_MODE": mode,
    }
    attrs.update({tag: "1" for tag in tags})
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(1, "032b"),
            "INIT": format(init, "016b"), "K": format(4, "032b"),
        },
        "attributes": attrs,
        "port_directions": directions,
        "connections": connections,
    }


def _design(cells, netnames):
    return {
        "creator": "typed register-input compiled fixture",
        "modules": {"top": {
            "attributes": {"top": 1}, "ports": {},
            "cells": cells,
            "netnames": {
                name: {"hide_name": 0, "bits": [bit], "attributes": {}}
                for name, bit in netnames.items()
            },
        }},
    }


def _run(tmp_path, name, design, *extra):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=" + str(DEVDB),
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


@pytest.mark.parametrize("name", ["state", "renamed_without_semantic_hint"])
def test_raw_dff_packs_to_exact_typed_i0_feedthrough(tmp_path, name):
    design = _design(
        {name: _raw_dff(name, 2, 3, 4)},
        {"clock": 2, "data": 3, "q": 4},
    )
    result, log, output = _run(tmp_path, "raw_" + name, design, "--pack-only")
    assert result.returncode == 0, log
    routed = json.loads(output.read_text(encoding="utf-8"))
    module = routed["modules"]["top"]
    assert len(module["cells"]) == 1
    packed = next(iter(module["cells"].values()))
    assert packed["type"] == "GENERIC_SLICE"
    assert packed["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == "LUT_FEEDTHROUGH_I0"
    assert int(packed["parameters"]["FF_USED"], 2) == 1
    assert int(packed["parameters"]["INIT"], 2) == 0xAAAA
    assert packed["connections"]["I"][0] == module["netnames"]["data"]["bits"][0]
    assert packed["connections"]["CLK"] == module["netnames"]["clock"]["bits"]
    assert packed["connections"]["Q"] == module["netnames"]["q"]["bits"]
    assert packed["connections"]["F"] == []


def test_two_same_clock_raw_feedthroughs_place_together(tmp_path):
    design = _design({
        "left": _raw_dff("left", 2, 3, 4, "X14Y8_SLICE0"),
        "right": _raw_dff("right", 2, 5, 6, "X14Y8_SLICE2"),
    }, {"clock": 2, "left_d": 3, "left_q": 4, "right_d": 5, "right_q": 6})
    result, log, output = _run(
        tmp_path, "two_same_clock", design, "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    routed = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    modes = {
        cell["attributes"].get("AGRV2K_REGISTER_INPUT_MODE")
        for cell in routed["cells"].values() if cell["type"] == "GENERIC_SLICE"
    }
    assert modes == {"LUT_FEEDTHROUGH_I0"}


@pytest.mark.parametrize(
    "name, init, lut_inputs, tags, expected",
    [
        ("compute", 0xCCCC, ("x", 3, "x", "x"), (), "LUT_COMPUTE_TO_FF"),
        ("registered_pad", 0xFF00, ("x", "x", "x", 3),
         ("agamemnon_registered_pad_input",), "REGISTERED_PAD_I3"),
        ("direct_d", 0x00FF, ("x", "x", "x", 4),
         ("agamemnon_direct_d_feedback",), "DIRECT_D_I3"),
    ],
)
def test_lut_dff_fusion_preserves_distinct_typed_semantics(
        tmp_path, name, init, lut_inputs, tags, expected):
    design = _design({
        "logic": _lut("logic", init, lut_inputs, 5, tags),
        "state": _raw_dff("state", 2, 5, 4),
    }, {"clock": 2, "data": 3, "q": 4, "lut_to_d": 5})
    result, log, output = _run(tmp_path, "fused_" + name, design, "--pack-only")
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    assert len(module["cells"]) == 1
    packed = next(iter(module["cells"].values()))
    assert packed["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == expected
    assert int(packed["parameters"]["FF_USED"], 2) == 1
    assert int(packed["parameters"]["INIT"], 2) == init


@pytest.mark.parametrize(
    "name, cell, reason",
    [
        ("unknown", _generic("FORGED_MODE"), "unknown AGRV2K_REGISTER_INPUT_MODE"),
        ("wrong_init", _generic("LUT_FEEDTHROUGH_I0", init=0xCCCC, inputs=(0,)),
         "requires INIT=0xAAAA"),
        ("wrong_pin", _generic("LUT_FEEDTHROUGH_I0", init=0xAAAA, inputs=(3,)),
         "data net on I[0] only"),
        ("f_used", _generic("LUT_FEEDTHROUGH_I0", init=0xAAAA, inputs=(0,), f_used=True),
         "requires unused F"),
        ("carry_inherit", _generic("LUT_FEEDTHROUGH_I0", init=0xAAAA,
                                   inputs=(0,), carry=True),
         "cannot inherit"),
        ("compute_stale_direct_tag",
         _generic("LUT_COMPUTE_TO_FF", init=0x00FF, own_q_i3=True,
                  tags=("agamemnon_direct_d_feedback",)),
         "cannot inherit"),
    ],
)
def test_fixed_bel_cannot_bypass_placer_or_preroute_drc(tmp_path, name, cell, reason):
    design = _design({"forged": cell}, {
        "clock": 2, "q": 20, "i0": 100, "i3": 103, "f": 30,
        "cin": 40, "cout": 41,
    })
    placed, place_log, _ = _run(
        tmp_path, name + "_place", design, "--no-route", "--placer", "heap",
    )
    assert placed.returncode != 0
    assert reason in place_log
    assert "Running router2" not in place_log

    routed, route_log, _ = _run(
        tmp_path, name + "_drc", design, "--no-place", "--router", "router2",
    )
    assert routed.returncode != 0
    assert reason in route_log
    assert "Running router2" not in route_log


def test_direct_d_site_policy_is_identical_at_heap_and_preroute_boundaries(tmp_path):
    def design_at(bel, *, explicit=True, tagged=False):
        cell = _generic(
                "DIRECT_D_I3", init=0x00FF, bel=bel, own_q_i3=True,
                tags=(("agamemnon_direct_d_feedback",) if tagged else ()),
            )
        if not explicit:
            cell["attributes"].pop("AGRV2K_REGISTER_INPUT_MODE")
        return _design({"state": cell}, {"clock": 2, "q": 20})

    rejected, place_log, _ = _run(
        tmp_path, "direct_bad_place", design_at("X14Y8_SLICE0"),
        "--no-route", "--placer", "heap",
    )
    assert rejected.returncode != 0
    assert "outside the qualified direct-D site/presentation pool" in place_log
    assert "Running router2" not in place_log

    rejected, route_log, _ = _run(
        tmp_path, "direct_bad_preroute", design_at("X14Y8_SLICE0"),
        "--no-place", "--router", "router2",
    )
    assert rejected.returncode != 0
    assert "outside the qualified direct-D site/presentation pool" in route_log
    assert "Running router2" not in route_log

    accepted, place_log, _ = _run(
        tmp_path, "direct_good_place", design_at("X14Y11_SLICE4"),
        "--no-route", "--placer", "heap",
    )
    assert accepted.returncode == 0, place_log

    accepted, route_log, _ = _run(
        tmp_path, "direct_good_preroute", design_at("X14Y11_SLICE4"),
        "--no-place", "--router", "router2",
    )
    assert accepted.returncode == 0, route_log
    assert "pre-route DRC verified 1 typed register-input requirement" in route_log

    accepted, place_log, _ = _run(
        tmp_path, "direct_tagged_legacy_place",
        design_at("X14Y11_SLICE4", explicit=False, tagged=True),
        "--no-route", "--placer", "heap",
    )
    assert accepted.returncode == 0, place_log

    accepted, route_log, _ = _run(
        tmp_path, "direct_tagged_legacy_preroute",
        design_at("X14Y11_SLICE4", explicit=False, tagged=True),
        "--no-place", "--router", "router2",
    )
    assert accepted.returncode == 0, route_log


def test_bad_cluster_member_rejects_before_placement(tmp_path):
    bad = _generic("FORGED_MODE", init=0, inputs=(), bel=None)
    bad["attributes"].pop("NEXTPNR_BEL", None)
    bad["attributes"].pop("BEL_STRENGTH", None)
    design = _design({
        "boundary_state": bad,
        "mcu_h0": {
            "hide_name": 0, "type": "MCU_DOUT", "parameters": {}, "attributes": {},
            "port_directions": {"DOUT": "input"}, "connections": {"DOUT": [20]},
        },
    }, {"clock": 2, "boundary_output": 20})
    result, log, _ = _run(tmp_path, "bad_cluster", design, "--pack-only")
    assert result.returncode != 0
    assert "relative cluster rejects malformed register input on 'boundary_state'" in log
    assert "unknown AGRV2K_REGISTER_INPUT_MODE" in log
    assert "Placing design" not in log
