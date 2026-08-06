import csv
import json
import os
from pathlib import Path
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
    assert physical["PIN_25"] == ("24", "6")
    assert physical["PIN_26"] == ("24", "7")
    assert physical["PIN_27"] == ("25", "8")
    assert physical["PIN_28"] == ("25", "9")

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
    arch = (ENGINE / "archgen.py").read_text()
    assert 'str(r.get("tier", "")).endswith("-fixed")' in arch


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
