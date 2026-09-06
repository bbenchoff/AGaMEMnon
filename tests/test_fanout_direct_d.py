"""Fanout reduction preserves the direct-D fusion edge, not all DFF inputs."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_uarch_direct_d_fusion import _observed_feedback


@pytest.mark.parametrize("axis,tag", [(2, "agamemnon_local_qin_feedback"), (3, "agamemnon_direct_d_feedback")])
def test_both_feedback_edges_survive_high_fanout_and_repeat(tmp_path, axis, tag):
    design = _observed_feedback()
    cells = design["modules"]["top"]["cells"]
    lut = cells["feedback0"]
    lut["attributes"] = {tag: "1"}
    lut["connections"]["I"][axis], lut["connections"]["I"][3] = lut["connections"]["I"][3], lut["connections"]["I"][axis]
    for bit in (10, 11):
        for index in range(12):
            cells[f"observer_{bit}_{index}"] = dict(type="LUT", parameters={"INIT": f"{0xaaaa:016b}"},
                port_directions={"I": "input", "Q": "output"},
                connections={"I": [bit, "0", "0", "0"], "Q": [100 + bit * 20 + index]})
    path = tmp_path / "both.json"
    path.write_text(json.dumps(design))
    script = Path(__file__).parents[1] / "agamemnon/engine/fanout_split.py"
    command = [sys.executable, str(script), str(path), "2"]
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads(path.read_text())
    updated = result["modules"]["top"]["cells"]
    assert updated["state0"]["connections"]["D"] == [11]
    assert updated["feedback0"]["connections"]["I"][axis] == 10
    for bit in (10, 11):
        for index in range(12):
            assert updated[f"observer_{bit}_{index}"]["connections"]["I"][0] != bit
    subprocess.run(command, check=True, capture_output=True)
    assert json.loads(path.read_text()) == result


@pytest.mark.parametrize("maxfo", [2, 4, 8])
@pytest.mark.parametrize("tagged", [True, False])
def test_fanout_preserves_only_tagged_own_q_register_edge(tmp_path, maxfo, tagged):
    design = _observed_feedback()
    cells = design["modules"]["top"]["cells"]
    if not tagged:
        cells["feedback0"]["attributes"] = {}
    for index in range(20):
        observer = json.loads(json.dumps(cells["observer0"]))
        observer["connections"]["Q"] = [100 + index]
        cells["extra%d" % index] = observer
    path = tmp_path / "input.json"
    path.write_text(json.dumps(design))
    script = Path(__file__).parents[1] / "agamemnon/engine/fanout_split.py"
    subprocess.run([sys.executable, str(script), str(path), str(maxfo)], check=True, capture_output=True)
    result = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert (result["state0"]["connections"]["D"] == [11]) is tagged
    assert result["feedback0"]["connections"]["I"][3] == 10
    assert all(result["extra%d" % i]["connections"]["I"][0] != 11 for i in range(20))
    drivers = {cell["connections"]["Q"][0]: cell for cell in result.values()
               if cell.get("type") == "LUT"}
    for i in range(20):
        bit = result["extra%d" % i]["connections"]["I"][0]
        seen = set()
        while bit != 11:
            assert bit not in seen
            seen.add(bit)
            buffer = drivers[bit]
            assert buffer["attributes"]["agamemnon_fanout_buffer"] == "1"
            assert int(buffer["parameters"]["INIT"], 2) == 0xaaaa
            bit = buffer["connections"]["I"][0]
