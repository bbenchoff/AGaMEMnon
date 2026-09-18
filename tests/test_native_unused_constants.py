"""Packing should reclaim generated constants whose last use was folded."""
import json

import pytest

from test_native_bram_unassigned_output import _design
from test_uarch_carry_drc import CarryJson, _run, _run_document


@pytest.fixture(autouse=True)
def enable_reclamation(monkeypatch):
    monkeypatch.setenv("AGRV2K_PRUNE_UNUSED_CONSTANTS", "1")


def _counter():
    design = CarryJson()
    for index, name in enumerate(design.feedback_registered_chain(4)):
        design.cells[name]["connections"]["A"] = [str(index % 2)]
    return design


@pytest.mark.parametrize("flag", [None, "0", "", "true"])
@pytest.mark.parametrize("replicate", [False, True])
def test_disabled_reclamation_preserves_original_packing(tmp_path, monkeypatch, flag, replicate):
    if flag is None:
        monkeypatch.delenv("AGRV2K_PRUNE_UNUSED_CONSTANTS", raising=False)
    else:
        monkeypatch.setenv("AGRV2K_PRUNE_UNUSED_CONSTANTS", flag)
    if replicate:
        monkeypatch.setenv("AGRV2K_LOCAL_CONSTANTS", "1")
    else:
        monkeypatch.delenv("AGRV2K_LOCAL_CONSTANTS", raising=False)
    result, transcript, output = _run(tmp_path, _counter())
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    slices = [cell for cell in cells.values() if cell["type"] == "GENERIC_SLICE"]
    assert len(slices) == (11 if replicate else 8)
    assert sum(int(cell["parameters"]["FF_USED"], 2) for cell in slices) == 4


@pytest.mark.parametrize("replicate", [False, True])
def test_folded_operands_do_not_leave_unused_generated_slices(tmp_path, monkeypatch, replicate):
    if replicate:
        monkeypatch.setenv("AGRV2K_LOCAL_CONSTANTS", "1")
    else:
        monkeypatch.delenv("AGRV2K_LOCAL_CONSTANTS", raising=False)
    result, transcript, output = _run(tmp_path, _counter())
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    slices = [cell for cell in cells.values() if cell["type"] == "GENERIC_SLICE"]
    # Four arithmetic/state members, one seed and the still-live shared D=1.
    assert len(slices) == 6
    assert sum(int(cell["parameters"]["FF_USED"], 2) for cell in slices) == 4
    users = {bit for cell in cells.values() for port, bits in cell["connections"].items()
             if cell["port_directions"].get(port) == "input" for bit in bits}
    for cell in slices:
        assert any(bit in users for port, bits in cell["connections"].items()
                   if cell["port_directions"].get(port) == "output" for bit in bits)


@pytest.mark.parametrize("replicate", [False, True])
@pytest.mark.parametrize("value", [0, 1])
def test_required_bram_constant_address_keeps_a_driver(tmp_path, monkeypatch, replicate, value):
    if replicate:
        monkeypatch.setenv("AGRV2K_LOCAL_CONSTANTS", "1")
    else:
        monkeypatch.delenv("AGRV2K_LOCAL_CONSTANTS", raising=False)
    monkeypatch.setenv("AGRV2K_BRAM_HARDCONST", "1")
    design = _design("X13Y4_BRAM")
    ram = design["modules"]["top"]["cells"]["ram"]
    ram["parameters"].update(PORTA_WIDTH="00000", PORTB_WIDTH="00000")
    for index in (10, 11):
        port = "AddressA[" + str(index) + "]"
        ram["connections"][port] = [str(value)]
        ram["port_directions"][port] = "input"
    result, transcript, output = _run_document(tmp_path, "bram_constant", design, "--pack-only")
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    address = cells["ram"]["connections"]["AddressA"]
    assert len(address) == 2
    for bit in address:
        drivers = [c for c in cells.values() if c["connections"].get("F") == [bit]]
        assert len(drivers) == 1
        assert int(drivers[0]["parameters"]["FF_USED"], 2) == 0
        assert int(drivers[0]["parameters"]["INIT"], 2) == (0xFFFF if value else 0)


@pytest.mark.parametrize("value", [0, 1])
@pytest.mark.parametrize("reserved_name", [False, True])
@pytest.mark.parametrize("keep", [False, True])
def test_imported_unused_constant_is_not_owned_by_cleanup(tmp_path, value, reserved_name, keep):
    design = _counter()
    name = ("$PACKER_VCC" if value else "$PACKER_GND") if reserved_name else "user_constant"
    bit = design.net("observed_user_constant")
    attrs = {"keep": "1", "BEL": "X14Y10_SLICE0"} if keep else {}
    design.cells[name] = dict(
        type="GENERIC_SLICE", attributes=attrs,
        parameters={"K": "100", "FF_USED": "0", "INIT": ("1" if value else "0") * 16},
        port_directions={"F": "output"}, connections={"F": [bit]})
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cell = json.loads(output.read_text())["modules"]["top"]["cells"][name]
    assert cell["connections"]["F"]
    assert int(cell["parameters"]["INIT"], 2) == (0xFFFF if value else 0)
    if keep:
        assert int(cell["attributes"]["keep"], 2) == 1
        assert cell["attributes"]["BEL"] == "X14Y10_SLICE0"
