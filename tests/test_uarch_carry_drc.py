"""Compiled behavior checks for dedicated-carry legalization and DRC.

These tests feed real Yosys-JSON-shaped cell graphs to an agrv2k nextpnr
binary.  They deliberately avoid source-text assertions: every negative must
be refused by the running packer before routing starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEVDB = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_tiered"


def _tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the compiled agrv2k nextpnr")
    if not (DEVDB / "dev_pips.csv").is_file():
        pytest.skip("emit the tiered agrv2k devdb before running compiled carry DRC tests")
    return executable


class CarryJson:
    def __init__(self):
        self.next_bit = 2
        self.cells = {}
        self.netnames = {}
        self.chains = []

    def net(self, name):
        bit = self.next_bit
        self.next_bit += 1
        self.netnames[name] = {
            "hide_name": 0, "bits": [bit], "attributes": {},
        }
        return bit

    def chain(self, length, name="c", *, first_bel=None, registered=False):
        carry = "0"
        cells = []
        for index in range(length):
            cout = self.net(f"{name}_cout_{index}")
            summ = self.net(f"{name}_sum_{index}")
            attrs = {}
            if index == 0 and first_bel is not None:
                attrs["BEL"] = first_bel
            cell_name = f"{name}_fa_{index}"
            self.cells[cell_name] = {
                "hide_name": 0,
                "type": "AG32_FA",
                "parameters": {},
                "attributes": attrs,
                "port_directions": {
                    "A": "input", "B": "input", "CIN": "input",
                    "COUT": "output", "SUM": "output",
                },
                "connections": {
                    "A": ["0"], "B": ["1"], "CIN": [carry],
                    "COUT": [cout], "SUM": [summ],
                },
            }
            cells.append(cell_name)
            carry = cout
        if registered:
            q = self.net(f"{name}_registered_q")
            self.cells[f"{name}_terminal_ff"] = {
                "hide_name": 0,
                "type": "DFF",
                "parameters": {},
                "attributes": {},
                "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
                "connections": {
                    "CLK": ["0"],
                    "D": self.cells[cells[-1]]["connections"]["SUM"],
                    "Q": [q],
                },
            }
        self.chains.append(cells)
        return cells

    def external_user(self, bit, name="external_lut"):
        out = self.net(f"{name}_out")
        self.cells[name] = {
            "hide_name": 0,
            "type": "LUT",
            "parameters": {"INIT": "0000000000001010"},
            "attributes": {},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [bit, "0", "0", "0"], "Q": [out]},
        }

    def write(self, path):
        design = {
            "creator": "AGaMEMnon compiled carry DRC fixture",
            "modules": {
                "top": {
                    "attributes": {"top": "00000000000000000000000000000001"},
                    "ports": {},
                    "cells": self.cells,
                    "netnames": self.netnames,
                }
            },
        }
        path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")


def _run(tmp_path, design, *, place=False):
    source = tmp_path / "carry.json"
    output = tmp_path / "result.json"
    design.write(source)
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    command = [
        _tool(), "--uarch", "agrv2k", "-o", f"chipdb={DEVDB}",
        "--json", str(source), "--write", str(output),
    ]
    command.append("--no-route" if place else "--pack-only")
    result = subprocess.run(
        command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


@pytest.mark.parametrize(
    ("length", "registered", "expected_cells"),
    [(4, False, 5), (4, True, 5), (24, False, 25), (32, False, 33)],
)
def test_admitted_linear_profiles_pack_with_seed_and_terminal_modes(
        tmp_path, length, registered, expected_cells):
    design = CarryJson()
    design.chain(length, registered=registered)
    result, log, output = _run(tmp_path, design)
    assert result.returncode == 0, log
    assert f"carry placement: 1 chain(s), {expected_cells} cells" in log
    assert f"({1 if registered else 0} registered)" in log
    packed = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    assert "$CARRY_SEED" in packed


def test_two_short_chains_are_independently_translatable_clusters(tmp_path):
    design = CarryJson()
    design.chain(3, "long_name")
    design.chain(3, "a")
    result, log, output = _run(tmp_path, design)
    assert result.returncode == 0, log
    assert "carry placement: 2 chain(s), 8 cells" in log
    assert log.count("independent relative cluster of 4 cells") == 2
    packed = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    assert {name for name in packed if name.startswith("$CARRY_SEED_")} == {
        "$CARRY_SEED_0", "$CARRY_SEED_1",
    }


def test_terminal_cout_may_feed_ordinary_logic(tmp_path):
    design = CarryJson()
    cells = design.chain(4)
    terminal_cout = design.cells[cells[-1]]["connections"]["COUT"][0]
    design.external_user(terminal_cout, "terminal_carry_flag")
    result, log, _ = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    assert "carry placement: 1 chain(s), 5 cells" in log
    assert "unsupported interior non-carry fanout" not in log


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("cycle", "contains no chain head"),
        ("branch", "branches to multiple AG32_FA.CIN users"),
        ("merged", "through non-COUT port SUM"),
        ("external", "unsupported interior non-carry fanout"),
        ("overlength", "one chain through 33 stages"),
    ],
)
def test_malformed_or_unsupported_graphs_fail_in_packing(tmp_path, mutation, message):
    design = CarryJson()
    cells = design.chain(33 if mutation == "overlength" else 3)
    if mutation == "cycle":
        terminal_cout = design.cells[cells[-1]]["connections"]["COUT"]
        design.cells[cells[0]]["connections"]["CIN"] = terminal_cout
    elif mutation == "branch":
        first_cout = design.cells[cells[0]]["connections"]["COUT"]
        design.cells[cells[2]]["connections"]["CIN"] = first_cout
    elif mutation == "merged":
        first_sum = design.cells[cells[0]]["connections"]["SUM"]
        design.cells[cells[1]]["connections"]["CIN"] = first_sum
    elif mutation == "external":
        first_cout = design.cells[cells[0]]["connections"]["COUT"][0]
        design.external_user(first_cout)
    result, log, _ = _run(tmp_path, design)
    assert result.returncode != 0
    assert message in log
    assert "Routing" not in log
    assert "fused " not in log


def test_unqualified_long_chain_translation_without_direct_seam_fails_before_routing(tmp_path):
    design = CarryJson()
    # The qualified 25-stage shape has a X20Y12->X20Y11 seam. Moving its
    # first arithmetic slice here translates that seam to X15Y5->X15Y4,
    # where the loaded graph deliberately has no direct COUT15->CIN0 pip.
    design.chain(24, first_bel="X15Y5_SLICE1")
    result, log, _ = _run(tmp_path, design, place=True)
    assert result.returncode != 0
    assert "has no dedicated" in log
    assert "Routing" not in log
