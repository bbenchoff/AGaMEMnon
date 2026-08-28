"""Compiled coverage for semantically inactive slice-clock canonicalization."""

import copy
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
DEFAULT_DEVDB = (
    ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
)


def _devdb():
    path = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", DEFAULT_DEVDB))
    if not (path / "dev_pips.csv").is_file():
        pytest.skip("set AGAMEMNON_UARCH_DEVDB to the matching generated devdb")
    return path


def _primitive(kind, port, direction, bit):
    return {
        "hide_name": 0,
        "type": kind,
        "parameters": {},
        "attributes": {},
        "port_directions": {port: direction},
        "connections": {port: [bit]},
    }


def _clock_source(bit):
    return _primitive("MCU_BUS_CLOCK", "CLK", "output", bit)


def _slice(ff_used, clock, output, init=0x6996, inputs=None):
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(int(ff_used), "032b"),
            "INIT": format(init, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": {
            "AGRV2K_REGISTER_INPUT_MODE": (
                "LUT_COMPUTE_TO_FF" if ff_used else "NONE"
            ),
        },
        "port_directions": {
            "Q": "output", "F": "output", "CLK": "input", "I": "input",
        },
        "connections": {
            "Q": [output] if ff_used else [],
            "F": [] if ff_used else [output],
            "CLK": [clock],
            "I": list(inputs or ["x", "x", "x", "x"]),
        },
    }


def _netlist(cells, nets):
    return {
        "creator": "inactive constant slice clock test",
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


def _run(tmp_path, name, netlist):
    nextpnr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not nextpnr or not Path(nextpnr).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    source = tmp_path / f"{name}.json"
    output = tmp_path / f"{name}_packed.json"
    source.write_text(json.dumps(netlist, sort_keys=True), encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [nextpnr, "--uarch", "agrv2k", "-o", f"chipdb={_devdb()}",
         "--json", str(source), "--write", str(output), "--pack-only"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    log = result.stdout + result.stderr
    return result, output, log


def _pack(tmp_path, name, netlist):
    result, output, log = _run(tmp_path, name, netlist)
    assert result.returncode == 0, log
    return json.loads(output.read_text(encoding="utf-8")), log


def _cells(packed):
    return packed["modules"]["top"]["cells"]


def _without_output_bit(cell):
    normalized = copy.deepcopy(cell)
    normalized["connections"]["F"] = []
    normalized["connections"]["Q"] = []
    return normalized


def test_rule_is_structural_and_runs_after_slice_fusion():
    source = UARCH.read_text(encoding="utf-8")
    body = source.split(
        "static void pack_inactive_constant_slice_clocks", 1
    )[1].split("static bool is_nextpnr_iob", 1)[0]
    assert 'ctx->id("GENERIC_SLICE")' in body
    assert 'ctx->id("FF_USED")' in body
    assert 'ctx->id("INIT")' not in body
    assert "is_fully_def" not in body and "std::all_of" not in body
    assert "int_or_default(cell->params, ff_used, 0) != 0" in body
    assert "disconnectPort(clk)" in body
    for forbidden in (
        "addsub", "zero_or_reset", "PACKER_GND_NET", "PACKER_VCC_NET", ".v\"", ".sv\"",
    ):
        assert forbidden not in body
    pack = source.split("void pack() override", 1)[1]
    assert pack.index("pack_nonlut_ffs(ctx)") < pack.index(
        "pack_inactive_constant_slice_clocks(ctx)"
    ) < pack.index("pack_mcu_edge(ctx)")


def test_combinational_constant_clock_is_removed_and_hard_gnd_survives(tmp_path):
    gnd, trimmed_out, control_out = 2, 3, 4
    shared_inputs = [10, 11, 12, 13]
    packed, log = _pack(
        tmp_path,
        "inactive_gnd",
        _netlist(
            {
                "gnd_source": _primitive("GND", "Y", "output", gnd),
                "comb_constant_clock": _slice(
                    False, gnd, trimmed_out, inputs=shared_inputs
                ),
                # An explicit undefined CLK gives this otherwise identical LUT
                # the same empty port representation after packing.
                "comb_no_clock": _slice(
                    False, "x", control_out, inputs=shared_inputs
                ),
                "mcu_hresp": _primitive("MCU_AHB_HRESP", "DOUT", "input", gnd),
            },
            {
                "gnd": gnd, "trimmed_out": trimmed_out, "control_out": control_out,
                **{f"shared_input_{index}": bit for index, bit in enumerate(shared_inputs)},
            },
        ),
    )
    cells = _cells(packed)
    assert "canonicalized 1 inactive slice clock connection(s)" in log
    assert cells["comb_constant_clock"]["connections"]["CLK"] == []
    assert cells["comb_no_clock"]["connections"]["CLK"] == []
    assert _without_output_bit(cells["comb_constant_clock"]) == _without_output_bit(
        cells["comb_no_clock"]
    )

    packer_gnd = cells["$PACKER_GND"]["connections"]["F"][0]
    assert cells["mcu_hresp"]["connections"]["DOUT"] == [packer_gnd]
    assert all(
        packer_gnd not in cell.get("connections", {}).get("CLK", [])
        for cell in cells.values()
    ), "an inactive GND clock would emit an impossible fabric-to-ClkMUX arc"


def test_registered_admitted_clock_remains_connected(tmp_path):
    clock, ff_a_out, ff_b_out, ff_c_out = 2, 6, 7, 8
    packed, log = _pack(
        tmp_path,
        "registered_clocks",
        _netlist(
            {
                "clock_source": _clock_source(clock),
                "registered_a": _slice(True, clock, ff_a_out),
                "registered_b": _slice(True, clock, ff_b_out),
                "registered_c": _slice(True, clock, ff_c_out),
            },
            {
                "clock": clock, "ff_a_out": ff_a_out,
                "ff_b_out": ff_b_out, "ff_c_out": ff_c_out,
            },
        ),
    )
    cells = _cells(packed)
    assert "canonicalized" not in log
    packed_clock = cells["clock_source"]["connections"]["CLK"][0]
    assert cells["registered_a"]["connections"]["CLK"] == [packed_clock]
    assert cells["registered_b"]["connections"]["CLK"] == [packed_clock]
    assert cells["registered_c"]["connections"]["CLK"] == [packed_clock]


@pytest.mark.parametrize("source_kind", ["GND", "VCC", "fabric"])
def test_registered_untyped_clock_sources_fail_closed(source_kind, tmp_path):
    clock, output = 2, 3
    if source_kind == "fabric":
        source = _slice(False, "x", clock, init=0xAAAA)
    else:
        source = _primitive(source_kind, "Y", "output", clock)
    result, _output, log = _run(
        tmp_path,
        "registered_untyped_" + source_kind.lower(),
        _netlist(
            {
                "clock_source": source,
                "registered_state": _slice(True, clock, output),
            },
            {"clock": clock, "output": output},
        ),
    )
    assert result.returncode != 0, log
    assert "clock closure rejects unclassified source" in log
    assert "canonicalized" not in log
