"""Generated carry and constant objects must preserve imported identities."""
import json

import pytest

from test_native_bram_unassigned_output import _design
from test_uarch_carry_drc import CarryJson, _run, _run_document


@pytest.mark.parametrize("replicate", [False, True])
@pytest.mark.parametrize("surface", ["cell", "net"])
@pytest.mark.parametrize("base", ["ordinary", "$PACKER_GND", "$PACKER_VCC", "$CARRY_SEED", "$CARRY_VCC"])
def test_generated_constant_and_seed_names_preserve_feedback(tmp_path, monkeypatch, replicate, surface, base):
    if replicate:
        monkeypatch.setenv("AGRV2K_LOCAL_CONSTANTS", "1")
    else:
        monkeypatch.delenv("AGRV2K_LOCAL_CONSTANTS", raising=False)
    design = CarryJson()
    fas = design.feedback_registered_chain(4)
    fa = fas[0]
    # Multiple consumers of each value force real local replication when
    # enabled; merely setting the flag on a one-consumer net proves nothing.
    for index, member in enumerate(fas):
        design.cells[member]["connections"]["A"] = [str(1 - index % 2)]
    name = base + ("_NET" if surface == "net" and base != "ordinary" else "")
    if surface == "cell":
        design.cells[name] = design.cells.pop("fb_ff_0")
    else:
        design.netnames[name] = design.netnames.pop("fb_q_0")
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    carry = cells[fa + "_CARRY"]
    for index, member in enumerate(fas):
        packed = cells[member + "_CARRY"]
        assert int(packed["parameters"]["FF_USED"], 2) == 1
        assert packed["connections"]["I"][1] == packed["connections"]["Q"][0]
        assert int(packed["parameters"]["INIT"], 2) == (0x3CC0 if index % 2 else 0xC3FC)
    seed = [c for c in cells.values()
            if c["connections"].get("COUT") == carry["connections"]["CIN"]]
    assert len(seed) == 1
    assert int(seed[0]["parameters"]["INIT"], 2) & 0xFF == 0
    d = carry["connections"]["I"][3]
    drivers = [c for c in cells.values() if c["connections"].get("F") == [d]]
    assert len(drivers) == 1
    assert int(drivers[0]["parameters"]["FF_USED"], 2) == 0
    assert int(drivers[0]["parameters"]["INIT"], 2) == 0xFFFF


@pytest.mark.parametrize("reserved", ["$CARRY_SEED", "$CARRY_VCC", "fb_fa_0_CARRY"])
def test_carry_generated_cells_avoid_occupied_suffixes(tmp_path, reserved):
    design = CarryJson()
    fa = design.feedback_registered_chain(1)[0]
    q = design.cells["fb_ff_0"]["connections"]["Q"][0]
    outputs = {}
    for suffix in ("", "_1", "_2"):
        name = reserved + suffix
        bit = design.net(name + "_output")
        outputs[name] = bit
        design.cells[name] = dict(
            type="GENERIC_SLICE", attributes={},
            parameters={"K": "100", "FF_USED": "0", "INIT": "1010101010101010"},
            port_directions={"I": "input", "F": "output"},
            connections={"I": [q, "x", "x", "x"], "F": [bit]})
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    for name in outputs:
        assert cells[name]["type"] == "GENERIC_SLICE"
        assert int(cells[name]["parameters"]["INIT"], 2) == 0xAAAA
        assert int(cells[name]["parameters"]["FF_USED"], 2) == 0
    carry = [c for c in cells.values() if c["connections"].get("CIN")
             and int(c["parameters"]["FF_USED"], 2)]
    assert len(carry) == 1
    assert carry[0]["connections"]["I"][1] == carry[0]["connections"]["Q"][0]
    assert all(carry[0]["connections"]["Q"][0] == cells[name]["connections"]["I"][0]
               for name in outputs)


@pytest.mark.parametrize("name", ["ordinary_enable", "$PACKER_GND_NET", "$PACKER_VCC_NET"])
@pytest.mark.parametrize("shared_constants", [False, True])
def test_bram_live_enable_does_not_alias_named_shared_constant(tmp_path, monkeypatch, name, shared_constants):
    monkeypatch.setenv("AGRV2K_BRAM_HARDCONST", "1")
    design = _design("X13Y4_BRAM")
    module = design["modules"]["top"]
    ram = module["cells"]["ram"]
    ram["parameters"].update(PORTA_WIDTH="00000", PORTB_WIDTH="00000")
    ram["connections"].update(WeA=[4], **{"DataInA[0]": [3]})
    ram["port_directions"].update(WeA="input", **{"DataInA[0]": "input"})
    if shared_constants:
        ram["connections"].update(ReA=["0"], ClkEn0=["1"])
        ram["port_directions"].update(ReA="input", ClkEn0="input")
    module["cells"]["enable"] = dict(
        type="GENERIC_SLICE", attributes={},
        parameters={"K": "100", "FF_USED": "0", "INIT": "1010101010101010"},
        port_directions={"I": "input", "F": "output"},
        connections={"I": [2, "x", "x", "x"], "F": [4]})
    module["netnames"][name] = dict(bits=[4], attributes={})
    result, transcript, output = _run_document(tmp_path, "bram_names", design, "--pack-only")
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    assert cells["ram"]["connections"]["WeA"] == cells["enable"]["connections"]["F"]
    assert cells["ram"]["connections"]["DataInA"]
    assert int(cells["enable"]["parameters"]["INIT"], 2) == 0xAAAA
