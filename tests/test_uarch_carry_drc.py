"""Compiled behavior checks for dedicated-carry legalization and DRC.

These tests feed real Yosys-JSON-shaped cell graphs to an agrv2k nextpnr
binary.  They deliberately avoid source-text assertions: every negative must
be refused by the running packer before routing starts.
"""

from __future__ import annotations

import json
import heapq
import os
from pathlib import Path
import re
import subprocess
import csv

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEVDB = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", str(
    ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_tiered")))


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

    def admitted_clock(self):
        name = "typed_mcu_bus_clock"
        if name in self.cells:
            return self.cells[name]["connections"]["CLK"][0]
        bit = self.net("typed_mcu_bus_clock")
        self.cells[name] = {
            "hide_name": 0,
            "type": "MCU_BUS_CLOCK",
            "parameters": {},
            "attributes": {},
            "port_directions": {"CLK": "output"},
            "connections": {"CLK": [bit]},
        }
        return bit

    def chain(self, length, name="c", *, first_bel=None, fixed_bels=None,
              registered=False, dff_bel=None):
        carry = "0"
        cells = []
        fixed_bels = dict(fixed_bels or {})
        if first_bel is not None:
            assert 0 not in fixed_bels
            fixed_bels[0] = first_bel
        for index in range(length):
            cout = self.net(f"{name}_cout_{index}")
            summ = self.net(f"{name}_sum_{index}")
            attrs = {}
            if index in fixed_bels:
                attrs["BEL"] = fixed_bels[index]
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
            clock = self.admitted_clock()
            q = self.net(f"{name}_registered_q")
            self.cells[f"{name}_terminal_ff"] = {
                "hide_name": 0,
                "type": "DFF",
                "parameters": {},
                "attributes": ({"BEL": dff_bel} if dff_bel else {}),
                "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
                "connections": {
                    "CLK": [clock],
                    "D": self.cells[cells[-1]]["connections"]["SUM"],
                    "Q": [q],
                },
            }
        self.chains.append(cells)
        return cells

    def fixed_slice(self, name, bel):
        out = self.net(f"{name}_out")
        self.cells[name] = {
            "hide_name": 0,
            "type": "LUT",
            "parameters": {"INIT": "0000000000001010"},
            "attributes": {"BEL": bel},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": ["0", "0", "0", "0"], "Q": [out]},
        }

    def feedback_registered_chain(self, length, name="fb"):
        cells = self.chain(length, name=name)
        clock = self.admitted_clock()
        for index, cell_name in enumerate(cells):
            q = self.net(f"{name}_q_{index}")
            self.cells[cell_name]["connections"]["B"] = [q]
            self.cells[f"{name}_ff_{index}"] = {
                "hide_name": 0,
                "type": "DFF",
                "parameters": {},
                "attributes": {},
                "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
                "connections": {
                    "CLK": [clock],
                    "D": self.cells[cell_name]["connections"]["SUM"],
                    "Q": [q],
                },
            }
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


def _run(tmp_path, design, *, place=False, route=False, extra=(), timeout=120):
    source = tmp_path / "carry.json"
    output = tmp_path / "result.json"
    design.write(source)
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    command = [
        _tool(), "--uarch", "agrv2k", "-o", f"chipdb={DEVDB}",
        "--json", str(source), "--write", str(output), *extra,
    ]
    if not route:
        command.append("--no-route" if place else "--pack-only")
    result = subprocess.run(
        command, cwd=ROOT, env=env, text=True, capture_output=True,
        timeout=timeout,
    )
    return result, result.stdout + result.stderr, output


def _run_document(tmp_path, name, document, *extra):
    source = tmp_path / f"{name}.json"
    output = tmp_path / f"{name}_result.json"
    source.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", f"chipdb={DEVDB}",
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def _net_for_bit(module, bit):
    matches = [net for net in module["netnames"].values()
               if bit in net.get("bits", ())]
    assert len(matches) == 1
    return matches[0]


def _routed_short_chain(tmp_path):
    design = CarryJson()
    design.chain(4)
    result, log, output = _run(tmp_path, design, route=True)
    assert result.returncode == 0, log
    return json.loads(output.read_text(encoding="utf-8"))


def test_generated_database_has_one_exact_typed_carry_resource_profile():
    pips = list(csv.DictReader((DEVDB / "dev_pips.csv").open(
        encoding="utf-8", newline="")))
    typed_types = {"CARRY", "CARRY_SEAM", "SLICE_QFB"}
    typed = [row for row in pips if row["type"] in typed_types]
    by_type = {
        kind: [row for row in typed if row["type"] == kind]
        for kind in ("CARRY", "CARRY_SEAM", "SLICE_QFB")
    }
    assert {kind: len(rows) for kind, rows in by_type.items()} == {
        "CARRY": 1980,
        "CARRY_SEAM": 3,
        "SLICE_QFB": 2112,
    }
    assert {row["delay_ns"] for row in by_type["CARRY"]} == {"0.05"}
    assert {row["delay_ns"] for row in by_type["SLICE_QFB"]} == {"0.401"}
    names = [row["name"] for row in pips]
    assert len(names) == len(set(names))
    qfb_names = {row["name"] for row in by_type["SLICE_QFB"]}
    assert not any(row["name"] in qfb_names and row["type"] == "ROUTE"
                   for row in pips)

    wires = list(csv.DictReader((DEVDB / "dev_wires.csv").open(
        encoding="utf-8", newline="")))
    assert sum(bool(re.search(r"_CARRY(?:IN|OUT)\d{2}$", row["name"]))
               for row in wires) == 4224


def test_carry_lookahead_collapse_remains_an_admissible_lower_bound():
    wires = {
        row["name"]: row
        for row in csv.DictReader((DEVDB / "dev_wires.csv").open(
            encoding="utf-8", newline=""))
    }
    pips = list(csv.DictReader((DEVDB / "dev_pips.csv").open(
        encoding="utf-8", newline="")))

    # Mirror the running uarch's exact lookahead-node key.  Local carry wires
    # intentionally collapse to one tile/type node, yielding a zero estimate
    # against a real 0.05 ns edge: optimistic for QoR, but still admissible.
    def node(wire):
        row = wires[wire]
        return row["x"], row["y"], row["type"]

    local = [row for row in pips if row["type"] == "CARRY"]
    assert local
    assert all(node(row["src"]) == node(row["dst"]) for row in local)
    assert all(0.0 <= float(row["delay_ns"]) for row in local)

    # The three retained seams cross lookahead nodes.  Rebuild the same
    # nonnegative collapsed graph and prove its shortest estimate never
    # exceeds the actual admitted seam edge.  No timing or Fmax claim follows.
    graph = {}
    for row in pips:
        source, destination = node(row["src"]), node(row["dst"])
        delay = float(row["delay_ns"])
        edges = graph.setdefault(source, {})
        edges[destination] = min(delay, edges.get(destination, delay))

    def shortest(source, destination):
        queue = [(0.0, source)]
        distance = {source: 0.0}
        while queue:
            value, current = heapq.heappop(queue)
            if value != distance[current]:
                continue
            if current == destination:
                return value
            for following, edge_delay in graph.get(current, {}).items():
                candidate = value + edge_delay
                if candidate < distance.get(following, float("inf")):
                    distance[following] = candidate
                    heapq.heappush(queue, (candidate, following))
        return float("inf")

    seams = [row for row in pips if row["type"] == "CARRY_SEAM"]
    assert len(seams) == 3
    for row in seams:
        estimate = shortest(node(row["src"]), node(row["dst"]))
        assert 0.0 <= estimate <= float(row["delay_ns"])


@pytest.mark.parametrize(
    ("length", "registered", "expected_cells"),
    [
        (4, False, 5), (4, True, 5),
        (9, False, 10), (24, False, 25),
        (25, False, 26), (32, False, 33),
    ],
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
    carry_profiles = {
        cell["attributes"]["AGRV2K_CARRY_PROFILE"]
        for cell in packed.values()
        if "AGRV2K_CARRY_PROFILE" in (cell.get("attributes") or {})
    }
    expected_profile = (
        "SHORT_LOCAL" if expected_cells <= 9 else
        "LEGACY_25" if expected_cells <= 25 else "LEGACY_33"
    )
    assert carry_profiles == {expected_profile}


def test_short_chain_router2_uses_only_exact_internal_carry_links(tmp_path):
    design = CarryJson()
    design.chain(4)
    result, log, _ = _run(tmp_path, design, route=True)
    assert result.returncode == 0, log
    assert ("post-route carry audit verified 1 chain(s), 4 internal link(s), "
            "0 Q-feedback net(s) with routed closure") in log


def test_import_accepts_only_the_exact_registered_q_feedback_resource(tmp_path):
    design = CarryJson()
    design.feedback_registered_chain(4)
    result, log, output = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    bel_pins = {
        (row["bel"], row["pin"]): row["wire"]
        for row in csv.DictReader((DEVDB / "dev_belpins.csv").open(
            encoding="utf-8", newline=""))
    }
    pips = {
        (row["src"], row["dst"]): row
        for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
    }
    routed = 0
    for cell in module["cells"].values():
        connections = cell.get("connections") or {}
        if not connections.get("CIN") or not connections.get("Q"):
            continue
        q_bit = connections["Q"][0]
        if connections["I"][1] != q_bit:
            continue
        bel = cell["attributes"]["NEXTPNR_BEL"]
        q_wire, b_wire = bel_pins[(bel, "Q")], bel_pins[(bel, "I[1]")]
        bridge = next(row for (src, _dst), row in pips.items()
                      if src == q_wire and row["type"] == "OMUXFB")
        qfb = pips[(bridge["dst"], b_wire)]
        assert qfb["type"] == "SLICE_QFB"
        net = _net_for_bit(module, q_bit)
        net.setdefault("attributes", {})["ROUTING"] = (
            f"{q_wire};;1;{bridge['dst']};{bridge['name']};1;"
            f"{b_wire};{qfb['name']};1"
        )
        routed += 1
    assert routed == 4
    document = {"modules": {"top": module}}
    result, log, _ = _run_document(
        tmp_path, "exact_qfb_import", document,
        "--no-pack", "--no-place", "--no-route")
    assert result.returncode == 0, log
    assert "typed resource notification rejects" not in log


def _ordinary_slice_qfb_document():
    bel = "X2Y2_SLICE3"
    bel_pins = {
        (row["bel"], row["pin"]): row["wire"]
        for row in csv.DictReader((DEVDB / "dev_belpins.csv").open(
            encoding="utf-8", newline=""))
    }
    pips = list(csv.DictReader((DEVDB / "dev_pips.csv").open(
        encoding="utf-8", newline="")))
    q_wire, b_wire = bel_pins[(bel, "Q")], bel_pins[(bel, "I[1]")]
    bridge = next(row for row in pips
                  if row["src"] == q_wire and row["type"] == "OMUXFB")
    qfb = next(row for row in pips
               if row["src"] == bridge["dst"] and row["dst"] == b_wire)
    assert qfb["type"] == "SLICE_QFB"
    module = {
        "attributes": {},
        "ports": {},
        "cells": {
            "typed_mcu_bus_clock": {
                "hide_name": 0,
                "type": "MCU_BUS_CLOCK",
                "parameters": {},
                "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_BUS_CLOCK"},
                "port_directions": {"CLK": "output"},
                "connections": {"CLK": [14]},
            },
            "ordinary_registered_feedback": {
                "hide_name": 0,
                "type": "GENERIC_SLICE",
                "parameters": {
                    "K": "00000000000000000000000000000100",
                    "FF_USED": "00000000000000000000000000000001",
                    "INIT": "1001011011101000",
                },
                "attributes": {"NEXTPNR_BEL": bel},
                "port_directions": {
                    "I": "input", "CLK": "input", "Q": "output",
                    "F": "output",
                },
                "connections": {
                    "I": [11, 10, 12, 13], "CLK": [14], "Q": [10],
                    "F": [],
                },
            },
        },
        "netnames": {
            "feedback": {
                "hide_name": 0,
                "bits": [10],
                "attributes": {"ROUTING": (
                    f"{q_wire};;1;{bridge['dst']};{bridge['name']};1;"
                    f"{b_wire};{qfb['name']};1"
                )},
            },
            "clk": {"hide_name": 0, "bits": [14], "attributes": {}},
        },
    }
    return {"modules": {"top": module}}, bridge, qfb


def test_import_accepts_semantically_owned_ordinary_slice_q_feedback(tmp_path):
    document, _bridge, _qfb = _ordinary_slice_qfb_document()
    result, log, _ = _run_document(
        tmp_path, "ordinary_slice_qfb", document,
        "--no-pack", "--no-place", "--no-route")
    assert result.returncode == 0, log
    assert "typed resource notification rejects" not in log


def test_import_rejects_partial_ordinary_slice_q_feedback_path(tmp_path):
    document, _bridge, _qfb = _ordinary_slice_qfb_document()
    net = document["modules"]["top"]["netnames"]["feedback"]
    parts = net["attributes"]["ROUTING"].split(";")
    net["attributes"]["ROUTING"] = ";".join(parts[:3] + parts[6:9])
    result, log, _ = _run_document(
        tmp_path, "partial_ordinary_slice_qfb", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0, log
    assert "slice Q-feedback closure is partial" in log


def test_import_rejects_slice_q_feedback_without_a_physical_ff_owner(tmp_path):
    document, bridge, qfb = _ordinary_slice_qfb_document()
    cell = document["modules"]["top"]["cells"]["ordinary_registered_feedback"]
    cell["parameters"]["FF_USED"] = "0" * 32
    result, log, _ = _run_document(
        tmp_path, "combinational_slice_qfb", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0, log
    # Both edges require the physical FF owner. Import may reject the bridge
    # first, before reaching the downstream feedback terminal.
    assert any("typed resource notification rejects PIP %s" % pip["name"] in log
               for pip in (bridge, qfb)), log


def test_complete_routed_import_survives_no_pack_preroute_and_postroute(tmp_path):
    document = _routed_short_chain(tmp_path)
    result, log, _ = _run_document(
        tmp_path, "complete_import", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode == 0, log
    assert "pre-route carry audit verified 1 chain(s), 4 internal link(s)" in log
    assert ("post-route carry audit verified 1 chain(s), 4 internal link(s), "
            "0 Q-feedback net(s) with routed closure") in log


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("missing", "unbound or unauthenticated member"),
        ("duplicate_position", "duplicate chain position"),
        ("wrong_role", "unbound or unauthenticated member"),
        ("wrong_profile", "unbound or unauthenticated member"),
    ],
)
def test_no_pack_import_rejects_tampered_persistent_carry_identity(
        tmp_path, mutation, message):
    document = _routed_short_chain(tmp_path)
    module = document["modules"]["top"]
    cells = module["cells"]
    # Exercise the aggregate metadata audit itself rather than allowing an
    # earlier imported-PIP notification to reject the now-inconsistent owner.
    for net in module["netnames"].values():
        (net.get("attributes") or {}).pop("ROUTING", None)
    members = sorted(
        (cell for cell in cells.values()
         if "AGRV2K_CARRY_POSITION" in (cell.get("attributes") or {})),
        key=lambda cell: int(cell["attributes"]["AGRV2K_CARRY_POSITION"]),
    )
    assert len(members) == 5
    if mutation == "missing":
        members[2]["attributes"].pop("AGRV2K_CARRY_SCHEMA")
    elif mutation == "duplicate_position":
        members[2]["attributes"]["AGRV2K_CARRY_POSITION"] = (
            members[1]["attributes"]["AGRV2K_CARRY_POSITION"]
        )
        members[2]["attributes"]["AGRV2K_CARRY_ROLE"] = (
            members[1]["attributes"]["AGRV2K_CARRY_ROLE"]
        )
    elif mutation == "wrong_role":
        members[2]["attributes"]["AGRV2K_CARRY_ROLE"] = "SEED"
    else:
        members[2]["attributes"]["AGRV2K_CARRY_PROFILE"] = "FOREIGN"
    result, log, _ = _run_document(
        tmp_path, "tampered_" + mutation, document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0, log
    assert message in log


def test_no_pack_import_rejects_carry_metadata_on_an_ordinary_cell(tmp_path):
    document = _routed_short_chain(tmp_path)
    cells = document["modules"]["top"]["cells"]
    carry = next(cell for cell in cells.values()
                 if "AGRV2K_CARRY_SCHEMA" in (cell.get("attributes") or {}))
    ordinary = next(cell for cell in cells.values()
                    if "CIN" not in (cell.get("connections") or {}) and
                    "COUT" not in (cell.get("connections") or {}) and
                    cell.get("type") == "GENERIC_SLICE")
    for key in (
        "AGRV2K_CARRY_SCHEMA", "AGRV2K_CARRY_PROFILE",
        "AGRV2K_CARRY_CHAIN", "AGRV2K_CARRY_POSITION",
        "AGRV2K_CARRY_LENGTH", "AGRV2K_CARRY_ROLE",
    ):
        ordinary.setdefault("attributes", {})[key] = carry["attributes"][key]
    result, log, _ = _run_document(
        tmp_path, "foreign_carry_metadata", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0, log
    assert "carry closure rejects metadata on non-carry cell" in log


def test_no_pack_import_rejects_wrong_retained_profile_with_legal_seam_pips(
        tmp_path):
    design = CarryJson()
    design.chain(24, first_bel="X20Y12_SLICE1")
    result, log, output = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    document = json.loads(output.read_text(encoding="utf-8"))
    module = document["modules"]["top"]
    ordered = sorted(
        (cell for cell in module["cells"].values()
         if "AGRV2K_CARRY_POSITION" in (cell.get("attributes") or {})),
        key=lambda cell: int(
            cell["attributes"]["AGRV2K_CARRY_POSITION"], 2),
    )
    assert len(ordered) == 25
    assert {cell["attributes"]["AGRV2K_CARRY_PROFILE"]
            for cell in ordered} == {"LEGACY_25"}

    # Rebind the complete chain to the graph-legal upward seam used by the
    # retained 33-site family, while leaving its authenticated profile as
    # LEGACY_25.  Every imported link is still a real typed CARRY/SEAM PIP, so
    # only the aggregate profile-geometry audit can reject this composition.
    for position, cell in enumerate(ordered):
        y = 11 if position < 16 else 12
        z = position if position < 16 else position - 16
        cell["attributes"]["NEXTPNR_BEL"] = f"X20Y{y}_SLICE{z}"
    module["cells"]["$CARRY_VCC"]["attributes"]["NEXTPNR_BEL"] = (
        "X1Y1_SLICE15"
    )

    bel_pins = {
        (row["bel"], row["pin"]): row["wire"]
        for row in csv.DictReader((DEVDB / "dev_belpins.csv").open(
            encoding="utf-8", newline=""))
    }
    pips = {
        (row["src"], row["dst"]): row
        for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
    }
    for before, after in zip(ordered, ordered[1:]):
        source = bel_pins[(before["attributes"]["NEXTPNR_BEL"], "COUT")]
        destination = bel_pins[(after["attributes"]["NEXTPNR_BEL"], "CIN")]
        pip = pips[(source, destination)]
        assert pip["type"] in {"CARRY", "CARRY_SEAM"}
        bit = before["connections"]["COUT"][0]
        net = _net_for_bit(module, bit)
        net.setdefault("attributes", {})["ROUTING"] = (
            f"{destination};{pip['name']};1;{source};;1"
        )
    result, log, _ = _run_document(
        tmp_path, "tampered_retained_geometry", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0, log
    assert "retained carry closure rejects profile geometry" in log


@pytest.mark.parametrize("resource_type", [
    "ROUTE", "CARRY_SEAM", "SLICE_QFB",
])
def test_imported_internal_carry_net_rejects_extra_or_wrong_same_net_resource(
        tmp_path, resource_type):
    document = _routed_short_chain(tmp_path)
    module = document["modules"]["top"]
    seed_bit = module["cells"]["$CARRY_SEED"]["connections"]["COUT"][0]
    net = _net_for_bit(module, seed_bit)
    used = set(net["attributes"]["ROUTING"].split(";"))
    row = next(
        row for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
        if row["type"] == resource_type and row["name"] not in used
    )
    net["attributes"]["ROUTING"] += ";%s;%s;1" % (row["dst"], row["name"])
    result, log, _ = _run_document(
        tmp_path, "wrong_" + resource_type.lower(), document,
        "--no-pack", "--no-place", "--no-route")
    assert result.returncode != 0
    assert "typed resource notification rejects PIP %s" % row["name"] in log


@pytest.mark.parametrize("resource_type", [
    "CARRY", "CARRY_SEAM", "SLICE_QFB",
])
def test_imported_unrelated_net_cannot_claim_any_protected_native_resource(
        tmp_path, resource_type):
    document = _routed_short_chain(tmp_path)
    module = document["modules"]["top"]
    ordinary = module["netnames"]["$CARRY_VCC_NET"]
    all_routes = {token for net in module["netnames"].values()
                  for token in (net.get("attributes") or {}).get(
                      "ROUTING", "").split(";")}
    row = next(
        row for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
        if row["type"] == resource_type and row["name"] not in all_routes
    )
    ordinary["attributes"]["ROUTING"] += ";%s;%s;1" % (
        row["dst"], row["name"])
    result, log, _ = _run_document(
        tmp_path, "ordinary_" + resource_type.lower(), document,
        "--no-pack", "--no-place", "--no-route")
    assert result.returncode != 0
    assert "typed resource notification rejects PIP %s" % row["name"] in log


def test_partial_imported_internal_link_rejects_before_router2(tmp_path):
    document = _routed_short_chain(tmp_path)
    module = document["modules"]["top"]
    seed_bit = module["cells"]["$CARRY_SEED"]["connections"]["COUT"][0]
    net = _net_for_bit(module, seed_bit)
    pip_types = {
        row["name"]: row["type"]
        for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
    }
    parts = net["attributes"]["ROUTING"].split(";")
    retained = []
    removed = 0
    for index in range(0, len(parts), 3):
        if pip_types.get(parts[index + 1]) == "CARRY":
            removed += 1
        else:
            retained.extend(parts[index:index + 3])
    assert removed == 1
    net["attributes"]["ROUTING"] = ";".join(retained)
    result, log, _ = _run_document(
        tmp_path, "partial_internal", document,
        "--no-pack", "--no-place", "--router", "router2")
    assert result.returncode != 0
    assert "pre-route carry closure lacks its exact routed PIP" in log
    assert "Routing complete" not in log


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


def _slice_location(cell):
    bel = cell["attributes"]["NEXTPNR_BEL"]
    match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
    assert match, bel
    return tuple(int(item) for item in match.groups())


def test_short_chain_uses_an_alternate_root_when_old_template_root_is_blocked(
        tmp_path):
    design = CarryJson()
    design.fixed_slice("old_root_blocker", "X15Y1_SLICE0")
    names = design.chain(4)
    result, log, output = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    ordered = [cells["$CARRY_SEED"]] + [cells[name + "_CARRY"] for name in names]
    locations = [_slice_location(cell) for cell in ordered]
    assert locations[0] != (15, 1, 0)
    assert {(x, y) for x, y, _ in locations} == {locations[0][:2]}
    assert [z for _, _, z in locations] == list(range(locations[0][2],
                                                       locations[0][2] + 5))


@pytest.mark.parametrize("first_bel", [
    "X1Y1_SLICE5",
    "X15Y1_SLICE5",
])
def test_timing_enabled_and_disabled_runs_admit_the_same_fixed_short_footprint(
        tmp_path, first_bel):
    expected_x, expected_y, first_z = re.fullmatch(
        r"X(\d+)Y(\d+)_SLICE(\d+)", first_bel
    ).groups()
    expected = [
        (int(expected_x), int(expected_y), z)
        for z in range(int(first_z) - 1, int(first_z) + 4)
    ]
    observed = []
    for extra in ((), ("--no-tmdriv",)):
        design = CarryJson()
        names = design.chain(4, first_bel=first_bel)
        result, log, output = _run(
            tmp_path, design, place=True, extra=extra)
        assert result.returncode == 0, log
        cells = json.loads(output.read_text(encoding="utf-8"))[
            "modules"]["top"]["cells"]
        ordered = ([cells["$CARRY_SEED"]] +
                   [cells[name + "_CARRY"] for name in names])
        observed.append([_slice_location(cell) for cell in ordered])
    assert observed == [expected, expected]


@pytest.mark.parametrize("first_bel", [
    "X1Y1_SLICE5",
    "X15Y1_SLICE5",
])
def test_equal_shape_alternate_roots_have_equal_compiled_local_carry_delay(
        tmp_path, first_bel):
    design = CarryJson()
    design.chain(4, first_bel=first_bel)
    result, log, output = _run(tmp_path, design, route=True)
    assert result.returncode == 0, log
    document = json.loads(output.read_text(encoding="utf-8"))
    pip_rows = {
        row["name"]: row
        for row in csv.DictReader((DEVDB / "dev_pips.csv").open(
            encoding="utf-8", newline=""))
    }
    carry_delays = []
    for net in document["modules"]["top"]["netnames"].values():
        parts = (net.get("attributes") or {}).get("ROUTING", "").split(";")
        for index in range(1, len(parts), 3):
            row = pip_rows.get(parts[index])
            if row is not None and row["type"] == "CARRY":
                carry_delays.append(float(row["delay_ns"]))
    assert carry_delays == [0.05] * 4


def test_consistent_partial_fixed_short_chain_normalizes_to_one_root(tmp_path):
    design = CarryJson()
    names = design.chain(4, fixed_bels={
        0: "X15Y1_SLICE5",
        2: "X15Y1_SLICE7",
    })
    result, log, output = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    ordered = [cells["$CARRY_SEED"]] + [cells[name + "_CARRY"] for name in names]
    assert [_slice_location(cell) for cell in ordered] == [
        (15, 1, z) for z in range(4, 9)
    ]


@pytest.mark.parametrize("also_fix_fa", [False, True])
def test_dff_only_or_matching_fa_dff_fixed_intent_binds_whole_chain(
        tmp_path, also_fix_fa):
    design = CarryJson()
    fixed = {3: "X15Y1_SLICE8"} if also_fix_fa else None
    names = design.chain(
        4, registered=True, fixed_bels=fixed, dff_bel="X15Y1_SLICE8")
    result, log, output = _run(tmp_path, design, place=True)
    assert result.returncode == 0, log
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    ordered = [cells["$CARRY_SEED"]] + [cells[name + "_CARRY"] for name in names]
    assert [_slice_location(cell) for cell in ordered] == [
        (15, 1, z) for z in range(4, 9)
    ]


def test_conflicting_fa_and_capture_dff_fixed_intent_rejects_before_mutation(
        tmp_path):
    design = CarryJson()
    design.chain(4, registered=True, fixed_bels={3: "X15Y1_SLICE8"},
                 dff_bel="X15Y1_SLICE9")
    result, log, _ = _run(tmp_path, design, place=True)
    assert result.returncode != 0
    assert "mutually inconsistent BEL constraints" in log
    assert "fused " not in log


def test_fixed_carry_footprint_rejects_future_foreign_bel_reservation(tmp_path):
    design = CarryJson()
    design.fixed_slice("future_fixed", "X15Y1_SLICE6")
    design.chain(4, fixed_bels={0: "X15Y1_SLICE5"})
    result, log, _ = _run(tmp_path, design, place=True)
    assert result.returncode != 0
    assert "fixed carry footprint overlaps foreign fixed cell 'future_fixed'" in log
    assert "fused " not in log


@pytest.mark.parametrize(
    "fixed_bels,message",
    [
        ({0: "X15Y1_SLICE5", 2: "X15Y2_SLICE7"},
         "mutually inconsistent BEL constraints"),
        ({0: "X15Y1_SLICE0"}, "implies an unavailable cluster root"),
        ({0: "X15Y1_SLICE15"}, "contains an unavailable member"),
    ],
)
def test_conflicting_or_out_of_range_short_fixed_intent_fails_before_mutation(
        tmp_path, fixed_bels, message):
    design = CarryJson()
    design.chain(4, fixed_bels=fixed_bels)
    result, log, _ = _run(tmp_path, design, place=True)
    assert result.returncode != 0
    assert message in log
    assert "fused " not in log


def test_unknown_fixed_short_bel_rejects_bounded(tmp_path):
    design = CarryJson()
    design.chain(4, first_bel="X7Y8_SLICE4")
    result, log, output = _run(tmp_path, design, place=True, timeout=5)
    assert result.returncode != 0
    assert "requests invalid slice BEL 'X7Y8_SLICE4'" in log
    assert "fused " not in log
    assert "Placer1" not in log
    assert not output.exists()


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
