import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ENGINE = ROOT / "agamemnon" / "engine"


def _rows(name):
    with (CHIPDB / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _netlist(path):
    cell = {
        "type": "GENERIC_IOB",
        "attributes": {},
        "port_directions": {"PAD": "inout", "O": "output", "I": "input", "EN": "input"},
        "connections": {"PAD": [10], "O": [20], "I": [21], "EN": [22]},
    }
    path.write_text(json.dumps({"modules": {"top": {
        "attributes": {"top": 1}, "ports": {"link": {"direction": "inout", "bits": [10]}},
        "cells": {"$iopadmap$top.link[0]": cell}, "netnames": {},
    }}}))


def _bind(tmp_path, pin):
    netlist = tmp_path / (pin + ".json")
    _netlist(netlist)
    pcf = tmp_path / (pin + ".pcf")
    pcf.write_text("set_io link %s\n" % pin)
    env = dict(os.environ, AGAMEMNON_DEVICE="AGRV2KL48")
    result = subprocess.run(
        [sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist), str(pcf), str(CHIPDB)],
        capture_output=True, text=True, env=env,
    )
    return result, netlist


def test_combined_iob_pcf_binding_is_characterization_gated(tmp_path):
    accepted, netlist = _bind(tmp_path, "PIN_16")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    cell = json.loads(netlist.read_text())["modules"]["top"]["cells"]["$iopadmap$top.link[0]"]
    assert cell["attributes"]["NEXTPNR_BEL"] == "X19Y13_IOB0"

    rejected, _ = _bind(tmp_path, "PIN_10")
    assert rejected.returncode != 0
    assert "bidirectional pin PIN_10 is not characterized" in rejected.stderr


def test_scalar_directions_bind_to_characterized_combined_iob_sites(tmp_path):
    for pin, directions, connections, expected in (
        ("PIN_25", {"PAD": "inout", "O": "output"},
         {"PAD": [10], "O": [20]}, "X0Y4_IOB0"),
        ("PIN_26", {"PAD": "inout", "I": "input"},
         {"PAD": [10], "I": [20]}, "X0Y4_IOB1"),
    ):
        netlist = tmp_path / (pin + "-scalar.json")
        _netlist(netlist)
        design = json.loads(netlist.read_text())
        cell = design["modules"]["top"]["cells"]["$iopadmap$top.link[0]"]
        cell["port_directions"] = directions
        cell["connections"] = connections
        netlist.write_text(json.dumps(design))
        pcf = tmp_path / (pin + "-scalar.pcf")
        pcf.write_text("set_io link %s\n" % pin)
        env = dict(os.environ, AGAMEMNON_DEVICE="AGRV2KL48")
        result = subprocess.run(
            [sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"),
             str(netlist), str(pcf), str(CHIPDB)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        rebound = json.loads(netlist.read_text())["modules"]["top"]["cells"]
        assert rebound["$iopadmap$top.link[0]"]["attributes"]["NEXTPNR_BEL"] == expected


def test_physical_iob_table_is_package_coherent_and_encodable():
    bonds = {r["pin"]: (r["x"], r["y"], r["z"]) for r in _rows("bondmap_L48.csv")}
    inputs = {(r["verified_pin"], r["pad_x"], r["pad_y"], r["inputmux"])
              for r in _rows("pad_input_L48.csv")}
    io_cells = {(r["x"], r["y"], r["mux"], r["sel"]) for r in _rows("pips_io.csv")}
    physical = _rows("physical_iob_L48.csv")
    assert {r["pin"] for r in physical} == {"PIN_16", "PIN_25", "PIN_26", "PIN_27", "PIN_28"}
    for row in physical:
        assert bonds[row["pin"]] == (row["x"], row["y"], row["z"])
        assert (row["pin"], row["x"], row["y"], row["inputmux"]) in inputs
        for sel in row["oe_sels"].split(";"):
            assert (row["cfg_x"], row["cfg_y"], row["oe_cfg"], sel) in io_cells


def test_left_pad_oe_terminals_use_isolated_vendor_route_feeders():
    physical = {r["pin"]: (r["oe_rmux"], r["oe_iomux"])
                for r in _rows("physical_iob_L48.csv")}
    assert physical["PIN_25"] == ("0", "6")
    assert physical["PIN_26"] == ("24", "7")
    assert physical["PIN_27"] == ("13", "8")
    assert physical["PIN_28"] == ("31", "9")

    edges = {(r["src_x"], r["src_y"], r["src_res"],
              r["dst_x"], r["dst_y"], r["dst_res"])
             for r in _rows("physical_iob_edges_L48.csv")}
    for rmux, iomux in (("RMUX24", "IOMUX06"), ("RMUX24", "IOMUX07"),
                        ("RMUX25", "IOMUX08"), ("RMUX25", "IOMUX09")):
        assert ("0", "4", rmux, "0", "4", iomux) in edges

    fixed = [r for r in _rows("physical_iob_edges_L48.csv")
             if r["tier"].endswith("-fixed")]
    assert fixed
    assert all(not r["cfg"] and r["source"] == "observed" for r in fixed)
    routing = (ENGINE / "features" / "routing.py").read_text()
    assert 'str(r.get("tier", "")).endswith("-fixed")' in routing


def test_synthesis_lowers_tristate_to_combined_generic_iob():
    script = (ROOT / "agamemnon" / "synth" / "synth_pads.tcl").read_text()
    assert "-tinoutpad GENERIC_IOB EN:O:I:PAD" in script
    arch = (ENGINE / "archgen.py").read_text()
    physical_io = (ENGINE / "features" / "physical_io.py").read_text()
    assert "PHYSICAL_IO_FEATURE.add_architecture" in arch
    assert 'ctx.addBelInput(bel=bel, name="EN", wire=enable_wire)' in physical_io


def test_l48_hse_function_pin_binds_to_typed_clkin(tmp_path):
    netlist = tmp_path / "hse.json"
    _netlist(netlist)
    design = json.loads(netlist.read_text())
    cell = design["modules"]["top"]["cells"]["$iopadmap$top.link[0]"]
    cell["port_directions"] = {"PAD": "inout", "O": "output"}
    cell["connections"] = {"PAD": [10], "O": [20]}
    netlist.write_text(json.dumps(design))
    pcf = tmp_path / "hse.pcf"
    pcf.write_text("set_io link PIN_HSE\n")
    env = dict(os.environ, AGAMEMNON_DEVICE="AGRV2KL48")
    result = subprocess.run(
        [sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist),
         str(pcf), str(CHIPDB)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cell = json.loads(netlist.read_text())["modules"]["top"]["cells"]["$iopadmap$top.link[0]"]
    assert cell["attributes"]["NEXTPNR_BEL"] == "CLKIN"


def test_hse_function_pin_rejects_bidirectional_and_unqualified_packages(tmp_path):
    bidir, _ = _bind(tmp_path, "PIN_HSE")
    assert bidir.returncode != 0
    assert "PIN_HSE requires a scalar input signal" in bidir.stderr

    netlist = tmp_path / "hse_l64.json"
    _netlist(netlist)
    # Turn the fixture into a scalar input pad cell.
    design = json.loads(netlist.read_text())
    cell = design["modules"]["top"]["cells"]["$iopadmap$top.link[0]"]
    cell["port_directions"] = {"PAD": "inout", "O": "output"}
    cell["connections"] = {"PAD": [10], "O": [20]}
    netlist.write_text(json.dumps(design))
    pcf = tmp_path / "hse_l64.pcf"
    pcf.write_text("set_io link PIN_HSE\n")
    env = dict(os.environ, AGAMEMNON_DEVICE="AGRV2KL64")
    result = subprocess.run(
        [sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist),
         str(pcf), str(CHIPDB)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    assert "PIN_HSE is not characterized for AGRV2KL64" in result.stderr


def test_quad_oe_corridors_are_complete_distinct_and_exactly_encodable():
    rows = _rows("pad_oe_L48_left_corridors.csv")
    assert len(rows) == 28
    by_link = {link: [r for r in rows if int(r["link"]) == link] for link in range(4)}
    assert {link: len(path) for link, path in by_link.items()} == {0: 6, 1: 8, 2: 7, 3: 7}
    assert {path[0]["source_bel"] for path in by_link.values()} == {
        "X10Y4_SLICE0", "X14Y12_SLICE0", "X14Y8_SLICE0", "X14Y4_SLICE0",
    }
    owners = set()
    fabric = {(r["x"], r["y"], r["mux"], r["sel"]) for r in _rows("pips_full.csv")}
    io = {(r["x"], r["y"], r["mux"], r["sel"]) for r in _rows("pips_io.csv")}
    for path in by_link.values():
        assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(path, path[1:]))
        owners.add(next(r["src_wire"] for r in reversed(path)
                        if r["src_wire"].startswith("X4Y4_RMUX")))
        for row in path:
            table = io if row["cell_table"] == "io" else fabric
            for sel in row["set_selectors"].split(";"):
                assert (row["x"], row["y"], row["cfg_group"], sel) in table
    assert owners == {"X4Y4_RMUX49", "X4Y4_RMUX63", "X4Y4_RMUX33", "X4Y4_RMUX20"}


def test_quad_link_input_corridors_and_hse_boundary_are_fail_closed():
    rows = _rows("pad_input_L48_left_corridors.csv")
    assert len(rows) == 8
    by_link = {link: [r for r in rows if int(r["link"]) == link] for link in range(4)}
    assert {path[0]["target_bel"] for path in by_link.values()} == {
        "X1Y4_SLICE2", "X1Y4_SLICE9",
    }
    for path in by_link.values():
        assert len(path) == 2
        assert path[0]["dst_wire"] == path[1]["src_wire"]
        assert path[0]["cell_table"] == ""
        assert path[1]["cell_table"] == "fabric"

    hse = next(r for r in _rows("pad_input_L48.csv") if r["verified_pin"] == "PIN_HSE")
    assert (hse["pad_x"], hse["pad_y"], hse["inputmux"],
            hse["dst_x"], hse["dst_y"], hse["dst_rmux"]) == \
           ("14", "13", "1", "14", "12", "8")
    assert hse["cfg"] == "CFG_RMUX1[3,9]"
    assert hse["set_cells"] == "-"

    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert "tie_left_link_data_gnd(ctx)" in uarch
    assert "pack_left_oe_quad(ctx)" in uarch
    assert "pack_left_link_inputs(ctx)" in uarch
    assert "if (!iob->ports.count(en_port))" in uarch
    assert "if (net == nullptr)" in uarch
    assert "PIN_%d OE has no fabric driver" in uarch
    assert "inserted exact PIN_%d OE identity presentation buffer" in uarch
    assert "bool requested_away" in uarch
    assert "requested_bel->second.as_string() != path.front().source_bel" in uarch
    assert "Scalar outputs share these physical BELs" in uarch
    assert "$single_link" in uarch
    assert "locked PIN_%d through one exact input identity" in uarch
    assert "AGRV2K_PAD_INPUT_IDENTITY" in uarch
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert '"pad_oe_L48_left_corridors.csv"' in cli
    assert '"pad_input_L48_left_corridors.csv"' in cli


def test_python_arch_exposes_and_encodes_plain_left_edge_inputs():
    """The exact link-input table must be usable outside the C++ uarch too."""
    physical = (ENGINE / "features" / "physical_io.py").read_text(encoding="utf-8")
    routing = (ENGINE / "features" / "routing.py").read_text(encoding="utf-8")
    assert 'left_input_path = root / "pad_input_L48_left_corridors.csv"' in physical
    assert 'ctx.addBelOutput(bel=bel, name="O", wire=wire)' in physical
    assert 're.fullmatch(r"X0Y4_IPAD[0-3]", bel)' in physical
    assert 'os.path.join(DATA, "pad_input_L48_left_corridors.csv")' in routing
    place = (ENGINE / "place_auto.py").read_text(encoding="utf-8")
    qin = (ENGINE / "qin_pack.py").read_text(encoding="utf-8")
    assert "_left_input_consumer_bels" in place
    assert "_claim_pin_bel" in place
    assert "incompatible exact" in place
    assert "both require exact bel" in place
    assert 'exact_targets[row["pin"]] = int(row["target_pin"])' in qin


def test_top_input_table_has_stable_optional_exact_pin_schema():
    path = CHIPDB / "pad_input_L48.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == [
            "pad_x", "pad_y", "inputmux", "dst_x", "dst_y", "dst_rmux",
            "cfg", "enable_byte", "enable_mask", "verified_pin", "set_cells",
            "clear_cells", "target_pin",
        ]
        rows = list(reader)

    # Appending target_pin must not shift any legacy row: an omitted value is
    # parsed as the empty optional field, never a None-key overflow.
    assert all(None not in row and row["target_pin"] is not None for row in rows)
    pin10 = next(row for row in rows if row["verified_pin"] == "PIN_10")
    assert pin10["target_pin"] == ""
    assert (pin10["cfg"], pin10["set_cells"], pin10["clear_cells"]) == \
           ("CFG_RMUX3[3,9]", "85:1", "")

    pin12 = next(row for row in rows if row["verified_pin"] == "PIN_12")
    assert pin12["target_pin"] == "2"
    assert (pin12["pad_x"], pin12["pad_y"], pin12["inputmux"],
            pin12["dst_x"], pin12["dst_y"], pin12["dst_rmux"]) == \
           ("20", "13", "7", "20", "12", "56")


def test_physical_graph_adds_dedicated_top_input_entries():
    routing = (ENGINE / "features" / "routing.py").read_text(encoding="utf-8")
    assert 'os.path.join(DATA, "pad_input_L48.csv")' in routing
    assert 'type="PADIN"' in routing
    assert '"InputMUX%02d" % int(_r["inputmux"])' in routing


def test_left_input_corridor_schema_matches_l48_bond_and_lut_targets():
    rows = list(csv.DictReader(
        (CHIPDB / "pad_input_L48_left_corridors.csv").open(newline="")
    ))
    bond = {
        row["pin"]: (int(row["x"]), int(row["y"]), int(row["z"]), row["edge"])
        for row in csv.DictReader((CHIPDB / "bondmap_L48.csv").open(newline=""))
    }
    for link in range(4):
        related = [row for row in rows if int(row["link"]) == link]
        fixed = [row for row in related if not row["cell_table"]]
        configurable = [row for row in related if row["cell_table"]]
        assert len(fixed) == len(configurable) == 1
        head, tail = fixed[0], configurable[0]
        assert bond[head["pin"]] == (0, 4, link, "LEFT")
        assert head["pin"] == tail["pin"]
        assert head["target_bel"] == tail["target_bel"]
        assert head["target_pin"] == tail["target_pin"]
        assert head["dst_wire"] == tail["src_wire"]
        match = re.fullmatch(r"X1Y4_SLICE(\d+)", head["target_bel"])
        assert match
        expected_imux = 4 * int(match.group(1)) + int(head["target_pin"])
        assert tail["dst_wire"] == "X1Y4_IMUX%02d" % expected_imux


def test_direct_pin25_witness_edge_is_admitted_after_silicon_control():
    target = ("RMUX68", "9", "4", "RMUX74", "11", "4")
    dead = {
        match.groups()
        for row in _rows("dead_edges_silicon.csv")
        if (match := re.fullmatch(
            r"(\w+)@(-?\d+),(-?\d+)->(\w+)@(-?\d+),(-?\d+)", row["edge"]
        ))
    }
    assert target not in dead
    assert any(
        (row["src_res"], row["src_x"], row["src_y"],
         row["dst_res"], row["dst_x"], row["dst_y"]) == target
        and row["cfg"] == "CFG_RMUX12[3,8]"
        for row in _rows("rrg_edges_full.csv")
    )


def test_all_four_left_input_corridors_have_scoped_silicon_evidence():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "left_input_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records
                  if row["trial_id"] ==
                  "left-input-pin25-through-pin28-direct-silicon-20260815")
    assert record["result"] == "pass"
    assert record["fcb_stat"] == "0x000f0002"
    assert set(record["pins"]) == {"PIN_25", "PIN_26", "PIN_27", "PIN_28"}
    assert {row["pico_gp"] for row in record["pins"].values()} == {12, 13, 16, 17}
    assert all(len(row["bitstream_sha256"]) == 64
               for row in record["pins"].values())
    assert "single-consumer" in record["scope"]
    assert "does not qualify" in record["scope"].lower()
