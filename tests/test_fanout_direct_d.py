"""Fanout reduction preserves the direct-D fusion edge, not all DFF inputs."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_uarch_direct_d_fusion import _observed_feedback


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
