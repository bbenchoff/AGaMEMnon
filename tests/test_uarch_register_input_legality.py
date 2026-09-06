"""Compiled AGRV2K register-input packing and hard legality boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEVDB = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB",
    str(ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict")))
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


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
             f_used=False, carry=False, own_q_i3=False, base=20):
    q, clk, f = base, 2, base + 10
    i = [base + 80 + index for index in range(4)]
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
    attrs = {"AGRV2K_REGISTER_INPUT_MODE": mode}
    if bel is not None:
        attrs.update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        })
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
    cells = dict(cells)
    clock_bits = sorted({
        bits[0]
        for cell in cells.values()
        for bits in [(cell.get("connections") or {}).get("CLK")]
        if (isinstance(bits, list) and len(bits) == 1
            and isinstance(bits[0], int) and not isinstance(bits[0], bool))
    })
    for index, bit in enumerate(clock_bits):
        cells["typed_mcu_bus_clock_%d" % index] = {
            "hide_name": 0,
            "type": "MCU_BUS_CLOCK",
            "parameters": {},
            "attributes": {},
            "port_directions": {"CLK": "output"},
            "connections": {"CLK": [bit]},
        }
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


def _run(tmp_path, name, design, *extra, local_constants=False):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("AGRV2K_LOCAL_CONSTANTS", None)
    if local_constants:
        env["AGRV2K_LOCAL_CONSTANTS"] = "1"
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=" + str(DEVDB),
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def _native_direct_design(count, *, occupied=(), clocks=None, declared=None):
    declared = count if declared is None else declared
    clocks = clocks or [2] * count
    cells = {}
    netnames = {}
    for index in range(count):
        base = 20 + 200 * index
        cell = _generic(
            "DIRECT_D_I3", init=0x00FF, bel=None, own_q_i3=True,
            tags=("agamemnon_direct_d_feedback",), base=base,
        )
        cell["connections"]["CLK"] = [clocks[index]]
        cell["attributes"].update({
            "agamemnon_direct_d_origin": "qin-pack-inferred-own-q",
            "AGRV2K_NATIVE_DIRECT_D_POOL": "X14Y11_SLICE4_7_V1",
            "AGRV2K_NATIVE_DIRECT_D_COUNT": str(declared),
        })
        cells["state%d" % index] = cell
        netnames["q%d" % index] = base
        netnames["clock%d" % clocks[index]] = clocks[index]
    for index, bel in enumerate(occupied):
        base = 2000 + 200 * index
        cells["occupied%d" % index] = _generic(
            "LUT_COMPUTE_TO_FF", init=0xAAAA, inputs=(0,), bel=bel, base=base,
        )
        netnames["occupied_q%d" % index] = base
        netnames["occupied_i%d" % index] = base + 80
    return _design(cells, netnames)


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
    packed_cells = [
        cell for cell in module["cells"].values()
        if cell["type"] == "GENERIC_SLICE"
    ]
    assert len(packed_cells) == 1
    packed = packed_cells[0]
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
    packed_cells = [
        cell for cell in module["cells"].values()
        if cell["type"] == "GENERIC_SLICE"
    ]
    assert len(packed_cells) == 1
    packed = packed_cells[0]
    assert packed["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == expected
    assert int(packed["parameters"]["FF_USED"], 2) == 1
    assert int(packed["parameters"]["INIT"], 2) == init


@pytest.mark.parametrize(
    "init, zero_inputs, connected_inputs, expected",
    [
        (0x0302, (1, 2), (0, 3), 0xFFAA),
        (0x0008, (2,), (0, 1, 3), 0x0088),
        (0x0004, (2,), (0, 1, 3), 0x0044),
        (0x00CA, (3,), (0, 1, 2), 0xCACA),
    ],
)
def test_defined_zero_slice_inputs_are_cofactored_before_disconnect(
        tmp_path, init, zero_inputs, connected_inputs, expected):
    cell = _generic(
        "LUT_COMPUTE_TO_FF", init=init, inputs=connected_inputs, bel=None,
    )
    cell["attributes"].pop("AGRV2K_REGISTER_INPUT_MODE")
    for index in zero_inputs:
        cell["connections"]["I"][index] = "0"
    design = _design(
        {"imported_slice": cell},
        {"clock": 2, "q": 20, **{
            "i%d" % index: 100 + index for index in connected_inputs
        }},
    )

    result, log, output = _run(
        tmp_path, "defined_zero_%04x" % init, design, "--pack-only",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    packed = module["cells"]["imported_slice"]
    assert int(packed["parameters"]["INIT"], 2) == expected
    driven_bits = {
        bit
        for candidate in module["cells"].values()
        for port, direction in candidate.get("port_directions", {}).items()
        if direction == "output"
        for bit in candidate.get("connections", {}).get(port, [])
        if isinstance(bit, int)
    }
    for index in zero_inputs:
        assert packed["connections"]["I"][index] not in driven_bits
    for row in range(16):
        defined_row = row
        for index in zero_inputs:
            defined_row &= ~(1 << index)
        assert ((init >> defined_row) & 1) == ((expected >> row) & 1)


def test_defined_zero_slice_cofactor_applies_without_any_opt_in(tmp_path):
    """The cofactor is a correctness fix, so it must not need an env flag.

    INIT 0x0008 asserts only row 3, so it DOES depend on I[2] -- row 7 is 0.
    Disconnecting a defined-zero I[2] while leaving INIT alone therefore leaves
    a slice that reads I[2] from nothing.  An undriven fabric input reads 1, so
    the slice would evaluate row 7 and output 0 forever.  This was the shape of
    the area_a_shift2_structural silicon escape.
    """
    cell = _generic(
        "LUT_COMPUTE_TO_FF", init=0x0008, inputs=(0, 1, 3), bel=None,
    )
    cell["attributes"].pop("AGRV2K_REGISTER_INPUT_MODE")
    cell["connections"]["I"][2] = "0"
    design = _design(
        {"imported_slice": cell},
        {"clock": 2, "q": 20, "i0": 100, "i1": 101, "i3": 103},
    )

    result, log, output = _run(
        tmp_path, "defined_zero_default", design, "--pack-only",
    )
    assert result.returncode == 0, log
    packed = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"][
        "imported_slice"
    ]
    # Row 7 is copied from row 3, so INIT no longer depends on the vanished input.
    assert int(packed["parameters"]["INIT"], 2) == 0x0088


def test_defined_zero_cofactor_call_is_not_gated_on_an_env_flag():
    """Guard against re-gating the cofactor behind AGRV2K_LOCAL_CONSTANTS.

    It was gated once, on the belief that "with the flag off, the existing
    validator rejects such imported slices".  It does not: that guard lived only
    in the LUT_COMPUTE_TO_FF branch, so purely combinational LUTs were never
    checked, and area_a_shift2_structural emitted release-strict clean while
    implementing the wrong function on 27 of its 31 command rows on silicon.
    """
    source = UARCH.read_text(encoding="utf-8")
    set_constant = source.split("static void set_net_constant", 1)[1].split(
        "static void replicate_local_constants", 1
    )[0]
    call = "cofactor_disconnected_zero_lut_input(ctx, uc, user.port);"
    assert call in set_constant
    assert "if (local_constants_enabled && !comb_clk_fold)" not in set_constant
    assert "if (!comb_clk_fold)" in set_constant


def test_combinational_slice_rejects_init_depending_on_a_disconnected_input(tmp_path):
    """The fail-closed net that was missing for FF_USED=0.

    Even with the cofactor in place, any OTHER route to a combinational slice
    whose INIT reads an input no net drives must refuse to build rather than
    emit a clean image that computes the wrong function.
    """
    cell = _generic("NONE", init=0xE4E4, inputs=(0, 2))
    cell["parameters"]["FF_USED"] = format(0, "032b")
    cell["connections"]["Q"] = []
    cell["connections"]["CLK"] = []
    cell["connections"]["F"] = [30]
    design = _design(
        {"comb_slice": cell},
        {"clock": 2, "f": 30, "i0": 100, "i2": 102},
    )
    # INIT 0xE4E4 depends on I[0], I[1] and I[2]; only I[0] and I[2] are
    # connected. The check lives in placement validity and the pre-route DRC,
    # NOT in packing -- so --pack-only passes it by, which is how the first
    # version of this test "proved" the guard absent when it was merely
    # unreached.
    result, log, _ = _run(
        tmp_path, "comb_undriven_init", design, "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0, log
    assert "INIT depends on an unconnected LUT input" in log


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (
            lambda cell: None,
            "LUT_COMPUTE_TO_FF: INIT depends on an unconnected LUT input",
        ),
        (
            lambda cell: cell["parameters"].pop("INIT"),
            "missing INIT parameter",
        ),
    ],
)
def test_forged_unconnected_compute_slice_remains_fail_closed(
        tmp_path, mutation, reason):
    bad = _generic(
        "LUT_COMPUTE_TO_FF", init=0x0008, inputs=(0, 1, 3), bel=None,
    )
    bad["attributes"].pop("NEXTPNR_BEL", None)
    bad["attributes"].pop("BEL_STRENGTH", None)
    mutation(bad)
    design = _design({
        "boundary_state": bad,
        "mcu_h0": {
            "hide_name": 0, "type": "MCU_DOUT", "parameters": {},
            "attributes": {},
            "port_directions": {"DOUT": "input"},
            "connections": {"DOUT": [20]},
        },
    }, {"clock": 2, "boundary_output": 20})

    result, log, _ = _run(
        tmp_path, "forged_unconnected_" + reason.split()[0].rstrip(":"), design,
        "--pack-only",
    )
    assert result.returncode != 0
    assert reason in log
    assert "Placing design" not in log


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
         "carry closure rejects unbound or unauthenticated member"),
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


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("seed", [1, 7, 29])
def test_native_direct_d_pool_heap_matches_distinct_qualified_sites(
        tmp_path, count, seed):
    result, log, output = _run(
        tmp_path, "native_%d_seed_%d" % (count, seed),
        _native_direct_design(count),
        "--no-route", "--placer", "heap", "--seed", str(seed),
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    bels = [cell["attributes"]["NEXTPNR_BEL"]
            for name, cell in module["cells"].items() if name.startswith("state")]
    assert len(bels) == count
    assert len(set(bels)) == count
    assert set(bels) <= {"X14Y11_SLICE4", "X14Y11_SLICE5",
                         "X14Y11_SLICE6", "X14Y11_SLICE7"}
    assert "matched %d native direct-D cell(s)" % count not in log  # no preRoute under --no-route


@pytest.mark.parametrize("replay_mode", ["late", "hard"])
@pytest.mark.parametrize("flow", [
    ("--no-route", "--placer", "heap"),
    ("--placer", "heap", "--router", "router2"),
])
def test_native_direct_d_pool_rejects_every_replay_bel_before_placement(
        tmp_path, monkeypatch, replay_mode, flow):
    replay = tmp_path / ("native_%s_placement.csv" % replay_mode)
    replay.write_text("state0,X14Y11_SLICE7\n", encoding="utf-8")
    monkeypatch.setenv("AGRV2K_REPLAY_BELS", str(replay))
    if replay_mode == "hard":
        monkeypatch.setenv("AGRV2K_REPLAY_BELS_HARD", "1")
    else:
        monkeypatch.delenv("AGRV2K_REPLAY_BELS_HARD", raising=False)

    result, log, _ = _run(
        tmp_path, "native_replay_%s_%s" % (
            replay_mode, "noroute" if flow[0] == "--no-route" else "router2",
        ), _native_direct_design(1), *flow,
    )
    assert result.returncode != 0
    assert "replay BEL map names native direct-D member 'state0'" in log
    assert "native members must be allocated only by HeAP" in log
    assert "Placing design" not in log
    assert "Running router2" not in log
    assert "bound 1 explicit direct-D" not in log
    assert "replay-bound 1 checkpoint BEL" not in log


@pytest.mark.parametrize("count", [1, 2, 3])
def test_native_direct_d_pool_allows_external_f_observers(tmp_path, count):
    design = _native_direct_design(count)
    module = design["modules"]["top"]
    for index in range(count):
        base = 20 + 200 * index
        f_bit = base + 10
        module["cells"]["state%d" % index]["connections"]["F"] = [f_bit]
        module["cells"]["observer%d" % index] = _lut(
            "observer%d" % index, 0xAAAA,
            (f_bit, "x", "x", "x"), 5000 + index,
        )
        module["netnames"]["f%d" % index] = {
            "hide_name": 0, "bits": [f_bit], "attributes": {},
        }
        module["netnames"]["observer%d_q" % index] = {
            "hide_name": 0, "bits": [5000 + index], "attributes": {},
        }
    result, log, _ = _run(
        tmp_path, "native_f_observers_%d" % count, design, "--pack-only",
    )
    assert result.returncode == 0, log


@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.parametrize("flow", [
    ("--pack-only",),
    ("--no-place", "--router", "router2"),
])
def test_native_direct_d_pool_rejects_external_q_consumers_before_router(
        tmp_path, hard, flow):
    design = _native_direct_design(1)
    module = design["modules"]["top"]
    if hard:
        module["cells"]["observer"] = {
            "hide_name": 0, "type": "MCU_DOUT", "parameters": {},
            "attributes": {}, "port_directions": {"DOUT": "input"},
            "connections": {"DOUT": [20]},
        }
    else:
        module["cells"]["observer"] = _lut(
            "observer", 0xAAAA, (20, "x", "x", "x"), 5000,
        )
        module["netnames"]["observer_q"] = {
            "hide_name": 0, "bits": [5000], "attributes": {},
        }
    result, log, _ = _run(
        tmp_path, "native_q_observer_%s_%s" % (
            "hard" if hard else "ordinary",
            "pack" if flow == ("--pack-only",) else "preroute",
        ), design, *flow,
    )
    assert result.returncode != 0
    assert "registered Q to be local-only" in log
    assert "Running router2" not in log


def test_native_direct_d_pool_uses_alternate_site_when_one_is_occupied(tmp_path):
    result, log, output = _run(
        tmp_path, "native_occupied", _native_direct_design(
            1, occupied=("X14Y11_SLICE4",)),
        "--no-route", "--placer", "heap", "--seed", "3",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    assert module["cells"]["state0"]["attributes"]["NEXTPNR_BEL"] in {
        "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7",
    }


def test_native_direct_d_pool_composes_with_explicit_member_and_occupancy(tmp_path):
    mixed = _native_direct_design(2)
    explicit = mixed["modules"]["top"]["cells"]["state1"]
    explicit["attributes"].pop("AGRV2K_NATIVE_DIRECT_D_POOL")
    explicit["attributes"].pop("AGRV2K_NATIVE_DIRECT_D_COUNT")
    explicit["attributes"]["agamemnon_direct_d_origin"] = "explicit-qualified-footprint"
    explicit["attributes"].update({
        "NEXTPNR_BEL": "X14Y11_SLICE4", "BEL_STRENGTH": format(5, "032b"),
    })
    result, log, output = _run(
        tmp_path, "native_mixed_explicit", mixed,
        "--no-route", "--placer", "heap", "--seed", "11",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    assert module["cells"]["state1"]["attributes"]["NEXTPNR_BEL"] == "X14Y11_SLICE4"
    assert module["cells"]["state0"]["attributes"]["NEXTPNR_BEL"] in {
        "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7",
    }

    occupied = _native_direct_design(3, occupied=("X14Y11_SLICE4",))
    result, log, output = _run(
        tmp_path, "native_three_one_occupied", occupied,
        "--no-route", "--placer", "heap", "--seed", "13",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    bels = {module["cells"]["state%d" % index]["attributes"]["NEXTPNR_BEL"]
            for index in range(3)}
    assert bels == {"X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7"}


def test_native_direct_d_pool_fails_closed_when_capacity_is_insufficient(tmp_path):
    result, log, _ = _run(
        tmp_path, "native_three_two_occupied", _native_direct_design(
            3, occupied=("X14Y11_SLICE4", "X14Y11_SLICE5")),
        "--no-route", "--placer", "heap", "--seed", "17",
    )
    assert result.returncode != 0
    assert "Running router2" not in log
    assert "placer-heap-cell-placement-timeout" in log


def test_native_direct_d_pool_preroute_drc_and_no_place_closure(tmp_path):
    routed, log, _ = _run(
        tmp_path, "native_routed", _native_direct_design(1),
        "--placer", "heap", "--router", "router2", "--seed", "5",
    )
    assert routed.returncode == 0, log
    assert "pre-route DRC matched 1 native direct-D cell(s)" in log

    unbound, log, _ = _run(
        tmp_path, "native_unbound", _native_direct_design(1),
        "--no-place", "--router", "router2",
    )
    assert unbound.returncode != 0
    assert (
        "has no bound BEL" in log
        or "pre-route clock closure rejects unplaced active slice" in log
    )
    assert "Running router2" not in log


def test_native_direct_d_pool_rejects_four_cells_and_clock_conflicts(tmp_path):
    four, log, _ = _run(
        tmp_path, "native_four", _native_direct_design(4, declared=3), "--pack-only",
    )
    assert four.returncode != 0
    assert "only exact 1..3-cell compositions are qualified" in log
    assert "Placing design" not in log

    clocks, log, _ = _run(
        tmp_path, "native_clock_conflict", _native_direct_design(2, clocks=[2, 3]),
        "--no-route", "--placer", "heap",
    )
    assert clocks.returncode != 0
    assert (
        "shared CLOCK" in log
        or "placer-heap-cell-placement-timeout" in log
        or "multiple whole-device clocks" in log
    )


@pytest.mark.parametrize("mutation, reason", [
    (lambda attrs: attrs.__setitem__("AGRV2K_NATIVE_DIRECT_D_POOL", "forged"),
     "unknown AGRV2K_NATIVE_DIRECT_D_POOL"),
    (lambda attrs: attrs.__setitem__("AGRV2K_NATIVE_DIRECT_D_COUNT", "4"),
     "must be exactly 1, 2, or 3"),
    (lambda attrs: attrs.__setitem__("agamemnon_direct_d_origin", "explicit"),
     "lacks exact inferred own-Q provenance"),
])
def test_malformed_native_direct_d_metadata_fails_before_no_place_router(
        tmp_path, mutation, reason):
    design = _native_direct_design(1)
    attrs = design["modules"]["top"]["cells"]["state0"]["attributes"]
    mutation(attrs)
    result, log, _ = _run(
        tmp_path, "native_malformed_" + reason.split()[0], design,
        "--no-place", "--router", "router2",
    )
    assert result.returncode != 0
    assert reason in log
    assert "Running router2" not in log


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
