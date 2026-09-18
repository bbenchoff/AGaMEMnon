"""Constant folding and write-input trimming must use drivers, not names."""
import json

import pytest

from devdb_fixtures import devdb_path
import test_uarch_carry_drc as carry_driver
from test_uarch_carry_drc import CarryJson, _run, _run_document
from test_native_bram_unassigned_output import _design


PHYSICAL_DEVDB = devdb_path("strict_pcf")


@pytest.fixture
def physical_io_database(monkeypatch):
    # The general native gate deliberately supplies a non-physical database.
    # These pads exist only in the separately generated physical-I/O profile.
    monkeypatch.setattr(carry_driver, "DEVDB", PHYSICAL_DEVDB)
    monkeypatch.setenv("AGRV2K_IO_PINPACK", "1")


@pytest.mark.parametrize("port,mask", [("A", 0xA5FA), ("B", 0x3CC0), ("CIN", 0x00AA)])
@pytest.mark.parametrize("name", ["ordinary", "PACKER_GND", "PACKER_VCC", "CARRY_VCC"])
def test_live_carry_input_is_not_folded_by_signal_name(tmp_path, port, mask, name):
    design = CarryJson()
    fa = design.feedback_registered_chain(1)[0]
    q = design.cells["fb_ff_0"]["connections"]["Q"][0]
    design.netnames["live_" + name + "_state"] = design.netnames.pop("fb_q_0")
    design.cells[fa]["connections"].update(A=["0"], B=["1"], CIN=["0"])
    design.cells[fa]["connections"][port] = [q]
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    carry = cells[fa + "_CARRY"]
    subject = cells["$CARRY_SEED"] if port == "CIN" else carry
    pin = 0 if port in ("A", "CIN") else 1
    assert subject["connections"]["I"][pin] == carry["connections"]["Q"][0]
    assert int(subject["parameters"]["INIT"], 2) == mask


@pytest.mark.parametrize("port", ["A", "B", "CIN"])
@pytest.mark.parametrize("value", [0, 1])
@pytest.mark.parametrize("replicate", [False, True])
def test_real_carry_constants_still_fold(tmp_path, monkeypatch, port, value, replicate):
    if replicate:
        monkeypatch.setenv("AGRV2K_LOCAL_CONSTANTS", "1")
    else:
        monkeypatch.delenv("AGRV2K_LOCAL_CONSTANTS", raising=False)
    design = CarryJson()
    fa = design.feedback_registered_chain(1)[0]
    q = design.cells["fb_ff_0"]["connections"]["Q"][0]
    connections = design.cells[fa]["connections"]
    if port == "B":
        connections["A"] = [q]
    connections[port] = [str(value)]
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    if port == "CIN":
        assert int(cells["$CARRY_SEED"]["parameters"]["INIT"], 2) == (0xFF if value else 0)
        return
    mask = int(cells[fa + "_CARRY"]["parameters"]["INIT"], 2)
    for state in (0, 1):
        for cin in (0, 1):
            for unused_pin in (0, 1):
                a, b = (unused_pin, state) if port == "A" else (state, unused_pin)
                address = a + 2*b + 4*cin
                total = state + value + cin
                assert (mask >> address) & 1 == int(total >= 2)
                assert (mask >> (8 + address)) & 1 == total % 2


@pytest.mark.parametrize("port", ["A", "B"])
@pytest.mark.parametrize("name", ["ordinary_source", "user_PACKER_GND_source"])
@pytest.mark.parametrize("shape", ["dynamic", "registered", "unknown", "zero", "one"])
def test_bram_write_data_depends_on_enable_driver(tmp_path, port, name, shape):
    document = _design("X13Y4_BRAM")
    module = document["modules"]["top"]
    ram = module["cells"]["ram"]
    ram["parameters"].update(PORTA_WIDTH="00000", PORTB_WIDTH="00000")
    ram["connections"].update({"We" + port: [4], "DataIn" + port + "[0]": [3]})
    ram["port_directions"].update({"We" + port: "input", "DataIn" + port + "[0]": "input"})
    registered = shape == "registered"
    output_port = "Q" if registered else "F"
    init = {"dynamic": "1010101010101010", "unknown": "xxxxxxxxxxxxxxxx",
            "zero": "0000000000000000", "one": "1111111111111111",
            "registered": "0000000000000000"}[shape]
    driver = dict(type="GENERIC_SLICE", attributes={},
                  parameters={"K": "100", "FF_USED": "1" if registered else "0", "INIT": init},
                  port_directions={"I": "input", output_port: "output"},
                  connections={"I": [2, "x", "x", "x"], output_port: [4]})
    if registered:
        driver["port_directions"]["CLK"] = "input"
        driver["connections"]["CLK"] = [3]
    module["cells"][name] = driver
    module["netnames"]["write_enable"] = dict(bits=[4], attributes={})
    result, transcript, output = _run_document(tmp_path, "bram", document, "--pack-only")
    assert result.returncode == 0, transcript
    ram = json.loads(output.read_text())["modules"]["top"]["cells"]["ram"]
    data = ram["connections"].get("DataIn" + port, [])
    assert bool(data) == (shape != "zero"), transcript


@pytest.mark.parametrize("name", ["ordinary_source", "user_PACKER_GND_source"])
@pytest.mark.parametrize("init", [0, 0xFFFF, 0xAAAA])
def test_left_io_data_uses_actual_constant_value(tmp_path, physical_io_database, name, init):
    document = _design("X13Y4_BRAM")
    module = document["modules"]["top"]
    module["cells"][name] = dict(
        type="GENERIC_SLICE", attributes={},
        parameters={"K": "100", "INIT": format(init, "016b"), "FF_USED": "0"},
        port_directions={"I": "input", "F": "output"},
        connections={"I": [2, "x", "x", "x"], "F": [4]})
    module["cells"]["pad"] = dict(
        type="GENERIC_IOB", parameters={},
        attributes={"NEXTPNR_BEL": "X0Y4_IOB0", "BEL": "X0Y4_IOB0"},
        port_directions={"I": "input"}, connections={"I": [4]})
    module["netnames"]["data"] = dict(bits=[4], attributes={})
    result, transcript, output = _run_document(tmp_path, "io", document, "--pack-only")
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    pad = cells["pad"]
    assert pad["attributes"]["NEXTPNR_BEL"] == "X0Y4_IOB0"
    assert bool(pad["connections"].get("I", [])) == (init != 0), transcript
    assert ("AGRV2K_IO_DATA_GND" in pad["attributes"]) == (init == 0), transcript
    if init != 0:
        # Normal output packing binds the live F source to the exact admitted
        # left-pad site. Its name must not replace this data with a zero tie.
        assert pad["connections"]["I"] == cells[name]["connections"]["F"]
        assert int(cells[name]["parameters"]["INIT"], 2) == init
        assert cells[name]["attributes"]["AGAMEMNON_SPECIAL_ROUTE_CLASS"] == "L48_LEFT_OUTPUT"


@pytest.mark.parametrize("name", ["ordinary_source", "user_PACKER_GND_source"])
def test_characterized_left_io_register_remains_live(tmp_path, physical_io_database, name):
    document = _design("X13Y4_BRAM")
    module = document["modules"]["top"]
    module["cells"][name] = dict(
        type="GENERIC_SLICE", attributes={"NEXTPNR_BEL": "X14Y11_SLICE4"},
        parameters={"K": "100", "INIT": format(0xAAAA, "016b"), "FF_USED": "1"},
        port_directions={"I": "input", "CLK": "input", "Q": "output"},
        connections={"I": [2, "x", "x", "x"], "CLK": [3], "Q": [4]})
    module["cells"]["pad"] = dict(
        type="GENERIC_IOB", parameters={},
        attributes={"NEXTPNR_BEL": "X0Y4_IOB0"},
        port_directions={"I": "input"}, connections={"I": [4]})
    module["netnames"]["data"] = dict(bits=[4], attributes={})
    result, transcript, output = _run_document(tmp_path, "registered_io", document, "--pack-only")
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    assert cells["pad"]["connections"]["I"] == cells[name]["connections"]["Q"]
    assert "AGRV2K_IO_DATA_GND" not in cells["pad"]["attributes"]
