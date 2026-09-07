"""Topology-only capture and witnessed Region for decomposed soft ripples."""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from devdb_fixtures import devdb_path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
WITNESS = ROOT / "agamemnon" / "chipdb" / "soft_ripple_region_witness.csv"
DEFAULT_DEVDB = devdb_path("strict", override="AGAMEMNON_TEST_SOFT_RIPPLE_DEVDB")


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_witness_is_the_retained_four_seed_topology_envelope():
    rows = list(csv.DictReader(WITNESS.open(encoding="utf-8", newline="")))
    assert rows == [{
        "scope": "bounded_shared_fanin_soft_ripple",
        "x_min": "14",
        "x_max": "19",
        "y_min": "8",
        "y_max": "11",
        "decoded_builds": "4",
        "chain_stages": "16",
        "max_slices_per_tile": "8",
        "provenance": "retained_four_seed_soft_ripple_endpoint_union",
    }]


def test_runtime_asset_is_fingerprinted_and_copied():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    runtime = _between(cli, "runtime_assets = (", "emit_context =")
    assert '"soft_ripple_region_witness.csv"' in runtime
    assert "runtime_asset, hashlib.sha256" in cli
    assert "shutil.copy(src_asset, devdb)" in cli


def test_capture_has_no_benchmark_name_or_path_dependency():
    source = UARCH.read_text(encoding="utf-8")
    capture = _between(
        source, "static void pack_shared_fanin_clusters", "static void pack_mcu_relative_clusters"
    )
    lowered = capture.lower()
    for forbidden in (
        "addsub", "operand_", "carry[", "unique_net", "ends_with",
        "name.str", "name.find", ".v\"", ".sv\"",
    ):
        assert forbidden not in lowered
    assert "identical_inputs" in capture
    assert "successors" in capture and "predecessors" in capture
    assert "sources == 1 && sinks == 1" in capture
    assert "registered_inputs" in capture
    assert "ambiguous soft-ripple topology" in capture
    assert "Do not expand it transitively" in capture
    assert "region_queue" not in capture
    assert "ctx->bindBel" not in capture
    assert "make_relative_cluster(ctx, shape, false)" in capture
    assert "ctx->createRectangularRegion" in capture
    assert "ctx->constrainCellToRegion" in capture


def _slice(ff_used, inputs, output, init, clock=None):
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(int(ff_used), "032b"),
            "INIT": format(init, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": {},
        "port_directions": {"Q": "output", "F": "output", "CLK": "input", "I": "input"},
        "connections": {
            "Q": [output] if ff_used else [],
            "F": [] if ff_used else [output],
            "CLK": [clock] if ff_used else [],
            "I": list(inputs),
        },
    }


def _mcu_input(primitive, output):
    return {
        "hide_name": 0,
        "type": primitive,
        "parameters": {},
        "attributes": {},
        "port_directions": {"DIN": "output"},
        "connections": {"DIN": [output]},
    }


def _synthetic_netlist(
    prefix, chain_lengths, with_second_order_neighbors=False, mcu_components=()
):
    cells = {}
    netnames = {}
    next_bit = 2

    def new_net(label):
        nonlocal next_bit
        bit = next_bit
        next_bit += 1
        netnames[f"{prefix}_{label}"] = {"hide_name": 0, "bits": [bit], "attributes": {}}
        return bit

    shared_clock = new_net("shared_clock")
    # N5.7A validates clock intent before topology capture.  Keep this
    # placement-focused fixture realistic by driving every registered stage
    # from the admitted MCU bus-clock primitive rather than an unowned net.
    cells[f"{prefix}_clock_source"] = {
        "hide_name": 0,
        "type": "MCU_BUS_CLOCK",
        "parameters": {},
        "attributes": {},
        "port_directions": {"CLK": "output"},
        "connections": {"CLK": [shared_clock]},
    }
    downstream_input = None
    for chain_index, length in enumerate(chain_lengths):
        previous = None
        for stage in range(length):
            upstream = None
            if with_second_order_neighbors and chain_index == 0 and stage == 0:
                upstream = new_net("second_order_upstream")
                cells[f"{prefix}_second_order_upstream"] = _slice(
                    False, ["0", "0", "0", "0"], upstream, 0x5A5A
                )
            left = new_net(f"c{chain_index}_r{stage}_left")
            right = new_net(f"c{chain_index}_r{stage}_right")
            cells[f"{prefix}_c{chain_index}_r{stage}_left"] = _slice(
                True, [upstream if upstream is not None else "0", "0", "0", "0"],
                left, 0xCA00, shared_clock
            )
            cells[f"{prefix}_c{chain_index}_r{stage}_right"] = _slice(
                True, ["0", "0", "0", "0"], right, 0xAC00, shared_clock
            )
            chain_output = new_net(f"c{chain_index}_s{stage}_link")
            side_output = new_net(f"c{chain_index}_s{stage}_side")
            stage_inputs = [left, right, previous if previous is not None else "0", "0"]
            cells[f"{prefix}_c{chain_index}_s{stage}_alpha"] = _slice(
                False, stage_inputs, chain_output, 0xB2E8
            )
            cells[f"{prefix}_c{chain_index}_s{stage}_beta"] = _slice(
                False, stage_inputs, side_output, 0x6996
            )
            if with_second_order_neighbors and chain_index == 0 and stage == 0:
                downstream_input = side_output
            previous = chain_output

    if with_second_order_neighbors:
        downstream_output = new_net("second_order_downstream")
        cells[f"{prefix}_second_order_downstream"] = _slice(
            False, [downstream_input, "0", "0", "0"], downstream_output, 0x3C3C
        )

    for label, primitive in mcu_components:
        source = new_net(f"{label}_mcu_source")
        output = new_net(f"{label}_logic_output")
        cells[f"{prefix}_{label}_mcu"] = _mcu_input(primitive, source)
        cells[f"{prefix}_{label}_logic"] = _slice(
            False, [source, "0", "0", "0"], output, 0x9669
        )

    return {
        "creator": "soft-ripple topology test",
        "modules": {
            "top": {
                "attributes": {"top": 1},
                "ports": {},
                "cells": cells,
                "netnames": netnames,
            }
        },
    }


def _pack_synthetic(tmp_path, name, netlist, devdb=None):
    nextpnr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not nextpnr or not Path(nextpnr).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    devdb = Path(devdb or os.environ.get(
        "AGAMEMNON_TEST_SOFT_RIPPLE_DEVDB",
        DEFAULT_DEVDB,
    ))
    if not (devdb / "soft_ripple_region_witness.csv").is_file():
        pytest.skip("prepare an isolated devdb containing the soft-ripple witness")

    source = tmp_path / f"{name}.json"
    output = tmp_path / f"{name}_packed.json"
    source.write_text(json.dumps(netlist), encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [nextpnr, "--uarch", "agrv2k", "-o", f"chipdb={devdb}",
         "--json", str(source), "--write", str(output), "--pack-only"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    return log


def test_pack_capture_is_rename_invariant(tmp_path):
    first = _pack_synthetic(tmp_path, "first", _synthetic_netlist("alpha", [16]))
    second = _pack_synthetic(tmp_path, "second", _synthetic_netlist("zeta", [16]))
    message = "captured 16-stage soft-ripple topology as 8 paired-stage cluster(s)"
    assert message in first
    assert message in second


def test_pack_capture_fails_closed_on_ambiguous_or_unrelated_shared_fanin(tmp_path):
    ambiguous = _pack_synthetic(
        tmp_path, "ambiguous", _synthetic_netlist("renamed", [16, 16])
    )
    unrelated = _pack_synthetic(
        tmp_path, "unrelated", _synthetic_netlist("independent", [15])
    )
    assert "ambiguous soft-ripple topology; leaving placement unchanged" in ambiguous
    assert "captured 16-stage soft-ripple topology" not in ambiguous
    assert "captured 16-stage soft-ripple topology" not in unrelated


def test_pack_region_excludes_second_order_data_neighbors(tmp_path):
    scoped = _pack_synthetic(
        tmp_path, "scoped", _synthetic_netlist(
            "arbitrary", [16], with_second_order_neighbors=True
        )
    )
    assert "(64 semantic cells: 32 consumers, 32 direct registered producers)" in scoped


def test_overlapping_broad_mcu_region_yields_to_active_topology_region(tmp_path):
    overlap = _pack_synthetic(
        tmp_path,
        "overlap",
        _synthetic_netlist(
            "unlabelled",
            [16],
            mcu_components=(("mcu_only", "MCU_AHB_HSIZE0"),),
        ),
    )
    assert "captured 16-stage soft-ripple topology" in overlap
    assert "broad heuristic MCU Region yields for 1-cell cone" in overlap
    assert "overlapping 1 active prior Region(s)" in overlap
    assert "hard endpoint/site/pin legality remains active" in overlap
    assert "native Region AGRV2K_MCU_CONE_0 constrains" not in overlap


def test_overlap_yields_only_that_component_and_nonoverlap_keeps_region(tmp_path):
    original_devdb = Path(os.environ.get(
        "AGAMEMNON_TEST_SOFT_RIPPLE_DEVDB",
        DEFAULT_DEVDB,
    ))
    split_devdb = tmp_path / "split_devdb"
    shutil.copytree(original_devdb, split_devdb)
    (split_devdb / "soft_ripple_region_witness.csv").write_text(
        "scope,x_min,x_max,y_min,y_max,decoded_builds,chain_stages,"
        "max_slices_per_tile,provenance\n"
        "bounded_shared_fanin_soft_ripple,14,19,6,8,4,16,8,"
        "synthetic_region_arbitration_geometry\n",
        encoding="utf-8",
    )
    split = _pack_synthetic(
        tmp_path,
        "split",
        _synthetic_netlist(
            "renamed",
            [16],
            mcu_components=(
                ("a_low", "MCU_SPI1_MOSI_OE"),
                ("z_high", "MCU_AHB_HSIZE0"),
            ),
        ),
        devdb=split_devdb,
    )
    assert "broad heuristic MCU Region yields for 1-cell cone at X14..15 Y6..8" in split
    assert (
        "native Region AGRV2K_MCU_CONE_0 constrains 1-cell MCU-fed cone to "
        "X14..15 Y10..12" in split
    )
    assert "native Region-constrained 1 MCU-fed cell(s) in 1 cone(s)" in split


def test_prior_region_overlap_is_slice_resource_compatible():
    source = UARCH.read_text(encoding="utf-8")
    regions = _between(source, "void constrain_mcu_regions()", "// ---- pack:")
    overlap = _between(
        regions,
        "for (Region *prior : prior_slice_regions)",
        "if (overlapping_prior_regions)",
    )
    assert "for (BelId bel : prior->bels)" in overlap
    assert "if (ctx->getBelType(bel) != slice_type)" in overlap
    assert "continue;" in overlap
    assert "loc.x >= x0 && loc.x <= x1 && loc.y >= y0 && loc.y <= y1" in overlap


def test_mcu_only_and_noncapture_designs_retain_broad_region_behavior(tmp_path):
    mcu_only = _pack_synthetic(
        tmp_path,
        "mcu_only",
        _synthetic_netlist(
            "standalone", [], mcu_components=(("cone", "MCU_AHB_HSIZE0"),)
        ),
    )
    assert "broad heuristic MCU Region yields" not in mcu_only
    assert "native Region AGRV2K_MCU_CONE_0 constrains 1-cell MCU-fed cone" in mcu_only

    noncapture = _pack_synthetic(
        tmp_path,
        "noncapture_mcu",
        _synthetic_netlist(
            "arbitrary", [15], mcu_components=(("cone", "MCU_AHB_HSIZE0"),)
        ),
    )
    assert "captured 16-stage soft-ripple topology" not in noncapture
    assert "broad heuristic MCU Region yields" not in noncapture
    assert "native Region AGRV2K_MCU_CONE_0 constrains 1-cell MCU-fed cone" in noncapture
