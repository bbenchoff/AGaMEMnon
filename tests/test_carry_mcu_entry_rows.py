"""A rigid carry chain may consume MCU inputs emerging on different rows."""
import json

from test_uarch_carry_drc import CarryJson, _run, _slice_location


def test_carry_chain_spans_input_entry_row_envelopes(tmp_path):
    design = CarryJson()
    names = design.chain(3)
    for name, lane in zip(names, (29, 30, 31)):
        bit = design.net(f"operand_{lane}")
        design.cells[f"mcu_haddr{lane}"] = {
            "type": "MCU_DIN", "parameters": {}, "attributes": {},
            "port_directions": {"DIN": "output"}, "connections": {"DIN": [bit]},
        }
        design.cells[name]["connections"]["A"] = [bit]
    result, log, output = _run(tmp_path, design, place=True, extra=("--placer", "heap"))
    assert result.returncode == 0, log
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    chain = [cells["$CARRY_SEED"]] + [cells[name + "_CARRY"] for name in names]
    locations = [_slice_location(cell) for cell in chain]
    assert len({(x, y) for x, y, z in locations}) == 1
    assert [z for x, y, z in locations] == list(range(locations[0][2], locations[0][2] + 4))
    for name, lane in zip(names, (29, 30, 31)):
        assert cells[name + "_CARRY"]["connections"]["I"][0] == cells[f"mcu_haddr{lane}"]["connections"]["DIN"][0]
