"""Compiled shared-clock control-set legality for AGRV2K slice tiles."""

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
        pytest.skip("emit the strict agrv2k devdb before running shared-clock tests")
    return executable


def _slice(ff_used, clock, output, *, bel=None, clock_mode="bound"):
    attributes = {}
    if bel is not None:
        attributes.update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        })
    port_directions = {
        "Q": "output", "F": "output", "CLK": "input", "I": "input",
    }
    connections = {
        "Q": [output] if ff_used else [],
        "F": [] if ff_used else [output],
        "CLK": [clock] if clock_mode == "bound" else ["x"],
        "I": ["x", "x", "x", "x"],
    }
    if clock_mode == "missing":
        del port_directions["CLK"]
        del connections["CLK"]
    elif clock_mode not in ("bound", "unbound"):
        raise ValueError(f"unknown clock mode: {clock_mode}")
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(int(ff_used), "032b"),
            "INIT": format(0x6996, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": attributes,
        "port_directions": port_directions,
        "connections": connections,
    }


def _slice_design(
        clock_a, clock_b, *, inactive_b=False, bels=(None, None), names=None,
        clock_modes=("bound", "bound")):
    names = names or ("state_a", "state_b", "clock_a", "clock_b")
    cell_a, cell_b, net_a, net_b = names
    return {
        "creator": "shared clock compiled fixture",
        "modules": {
            "top": {
                "attributes": {"top": 1},
                "ports": {},
                "cells": {
                    cell_a: _slice(
                        True, clock_a, 20, bel=bels[0], clock_mode=clock_modes[0]
                    ),
                    cell_b: _slice(
                        not inactive_b, clock_b, 21, bel=bels[1],
                        clock_mode=clock_modes[1]
                    ),
                },
                "netnames": {
                    net_a: {"hide_name": 0, "bits": [clock_a], "attributes": {}},
                    net_b: {"hide_name": 0, "bits": [clock_b], "attributes": {}},
                    "q_a": {"hide_name": 0, "bits": [20], "attributes": {}},
                    "q_b": {"hide_name": 0, "bits": [21], "attributes": {}},
                },
            }
        },
    }


def _carry_design(clock_bits):
    cells = {}
    netnames = {}
    carry = "0"
    next_bit = 10
    for index, clock in enumerate(clock_bits):
        summ, cout, q = next_bit, next_bit + 1, next_bit + 2
        next_bit += 3
        fa = f"arithmetic_{index}"
        cells[fa] = {
            "hide_name": 0,
            "type": "AG32_FA",
            "parameters": {},
            "attributes": {},
            "port_directions": {
                "A": "input", "B": "input", "CIN": "input",
                "COUT": "output", "SUM": "output",
            },
            "connections": {
                "A": ["0"], "B": ["1"], "CIN": [carry],
                "COUT": [cout], "SUM": [summ],
            },
        }
        cells[f"register_{index}"] = {
            "hide_name": 0,
            "type": "DFF",
            "parameters": {},
            "attributes": {},
            "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [clock], "D": [summ], "Q": [q]},
        }
        for name, bit in ((f"sum_{index}", summ), (f"carry_{index}", cout),
                          (f"q_{index}", q)):
            netnames[name] = {"hide_name": 0, "bits": [bit], "attributes": {}}
        carry = cout
    for index, clock in enumerate(sorted(set(clock_bits))):
        netnames[f"domain_{index}"] = {
            "hide_name": 0, "bits": [clock], "attributes": {},
        }
    return {
        "creator": "shared clock relative cluster fixture",
        "modules": {
            "top": {
                "attributes": {"top": 1}, "ports": {},
                "cells": cells, "netnames": netnames,
            }
        },
    }


def _boundary_design(ff_used, clock_mode):
    return {
        "creator": "shared clock MCU boundary cluster fixture",
        "modules": {
            "top": {
                "attributes": {"top": 1},
                "ports": {},
                "cells": {
                    "boundary_state": _slice(
                        ff_used, 2, 20, clock_mode=clock_mode,
                    ),
                    "mcu_h0": {
                        "hide_name": 0,
                        "type": "MCU_DOUT",
                        "parameters": {},
                        "attributes": {},
                        "port_directions": {"DOUT": "input"},
                        "connections": {"DOUT": [20]},
                    },
                },
                "netnames": {
                    "clock": {"hide_name": 0, "bits": [2], "attributes": {}},
                    "boundary_output": {
                        "hide_name": 0, "bits": [20], "attributes": {},
                    },
                },
            }
        },
    }


def _run(tmp_path, name, design, *extra, env_extra=None):
    source = tmp_path / f"{name}.json"
    output = tmp_path / f"{name}_out.json"
    source.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    env.update(env_extra or {})
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", f"chipdb={DEVDB}",
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def test_same_clock_composes_in_one_tile(tmp_path):
    design = _slice_design(
        2, 2, bels=("X14Y8_SLICE0", "X14Y8_SLICE2")
    )
    result, log, _ = _run(tmp_path, "same_clock", design, "--no-route", "--placer", "heap")
    assert result.returncode == 0, log


def test_different_clocks_are_independent_across_tiles(tmp_path):
    design = _slice_design(
        2, 3, bels=("X14Y8_SLICE0", "X15Y8_SLICE0")
    )
    result, log, _ = _run(tmp_path, "different_tiles", design, "--no-route", "--placer", "heap")
    assert result.returncode == 0, log


def test_placer_occupancy_rejects_different_clocks_in_one_tile(tmp_path):
    design = _slice_design(2, 3)
    result, log, _ = _run(
        tmp_path, "dense_conflict", design, "--no-route", "--placer", "heap",
        env_extra={"AGRV2K_DENSE_TILE": "14,8"},
    )
    assert result.returncode != 0
    assert "incompatible shared CLOCK" in log or "requires shared CLOCK net" in log
    assert "Running router2" not in log


def test_inactive_slice_does_not_consume_a_shared_clock(tmp_path):
    design = _slice_design(
        2, 3, inactive_b=True,
        bels=("X14Y8_SLICE0", "X14Y8_SLICE2"),
    )
    result, log, _ = _run(tmp_path, "inactive", design, "--no-route", "--placer", "heap")
    assert result.returncode == 0, log


@pytest.mark.parametrize(
    "clock_mode, reason",
    [("missing", "missing CLK port"), ("unbound", "CLK port has no bound net")],
)
def test_placer_rejects_malformed_active_registered_slice(tmp_path, clock_mode, reason):
    design = _slice_design(
        2, 3, inactive_b=True,
        bels=("X14Y8_SLICE0", "X14Y8_SLICE2"),
        clock_modes=(clock_mode, "bound"),
    )
    result, log, _ = _run(
        tmp_path, f"placer_malformed_{clock_mode}", design,
        "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0
    assert "active registered slice 'state_a'" in log
    assert reason in log
    assert "Running router2" not in log


@pytest.mark.parametrize("clock_mode", ["missing", "unbound"])
def test_inactive_slice_with_malformed_clock_shape_remains_inert(tmp_path, clock_mode):
    design = _slice_design(
        2, 3, inactive_b=True,
        bels=("X14Y8_SLICE0", "X14Y8_SLICE2"),
        clock_modes=("bound", clock_mode),
    )
    result, log, _ = _run(
        tmp_path, f"inactive_{clock_mode}", design, "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log


@pytest.mark.parametrize(
    "clock_mode, reason",
    [("missing", "missing CLK port"), ("unbound", "CLK port has no bound net")],
)
def test_relative_cluster_rejects_malformed_active_registered_slice(
        tmp_path, clock_mode, reason):
    result, log, _ = _run(
        tmp_path, f"cluster_malformed_{clock_mode}",
        _boundary_design(True, clock_mode), "--pack-only",
    )
    assert result.returncode != 0
    assert (
        "relative cluster rejects malformed active registered slice "
        "'boundary_state'"
    ) in log
    assert reason in log
    assert "Placing design" not in log


@pytest.mark.parametrize("clock_mode", ["missing", "unbound"])
def test_relative_cluster_keeps_inactive_malformed_clock_shape_inert(
        tmp_path, clock_mode):
    result, log, _ = _run(
        tmp_path, f"cluster_inactive_{clock_mode}",
        _boundary_design(False, clock_mode), "--pack-only",
    )
    assert result.returncode == 0, log
    assert "formed 1 native MCU relative cluster" in log


@pytest.mark.parametrize(
    "names",
    [
        ("state_a", "state_b", "clock_a", "clock_b"),
        ("renamed_left", "renamed_right", "alpha", "omega"),
    ],
)
def test_user_bel_constraints_fail_closed_under_renaming(tmp_path, names):
    design = _slice_design(
        2, 3, bels=("X14Y8_SLICE0", "X14Y8_SLICE2"), names=names,
    )
    result, log, _ = _run(
        tmp_path, "user_bel_" + names[0], design, "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0
    assert "requires shared CLOCK net" in log
    assert "Running router2" not in log


@pytest.mark.parametrize("clock_bits, should_pass", [((2, 2), True), ((2, 3), False)])
def test_relative_cluster_clock_compatibility_is_hard_at_pack_time(
        tmp_path, clock_bits, should_pass):
    result, log, _ = _run(
        tmp_path, f"carry_cluster_{clock_bits[0]}_{clock_bits[1]}",
        _carry_design(clock_bits), "--pack-only",
    )
    assert (result.returncode == 0) is should_pass, log
    if should_pass:
        assert "carry placement: 1 chain(s), 3 cells" in log
    else:
        assert "relative cluster has incompatible shared CLOCK requirements" in log
        assert "Placing design" not in log


def test_final_pre_route_drc_rechecks_locked_occupants(tmp_path):
    design = _slice_design(
        2, 3, bels=("X14Y8_SLICE0", "X14Y8_SLICE2")
    )
    result, log, _ = _run(tmp_path, "final_drc", design, "--no-place", "--router", "router2")
    assert result.returncode != 0
    assert "pre-route DRC rejects tile X14Y8" in log
    assert "Running router2" not in log


@pytest.mark.parametrize(
    "clock_mode, reason",
    [("missing", "missing CLK port"), ("unbound", "CLK port has no bound net")],
)
def test_final_pre_route_drc_rejects_malformed_active_register(
        tmp_path, clock_mode, reason):
    design = _slice_design(
        2, 3, inactive_b=True,
        bels=("X14Y8_SLICE0", "X14Y8_SLICE2"),
        clock_modes=(clock_mode, "bound"),
    )
    result, log, _ = _run(
        tmp_path, f"final_malformed_{clock_mode}", design,
        "--no-place", "--router", "router2",
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects malformed active registered slice 'state_a'" in log
    assert reason in log
    assert "Running router2" not in log
