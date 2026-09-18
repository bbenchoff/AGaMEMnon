"""Reject unreachable slice pairs even when the driver's fanout graph is large."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from devdb_fixtures import devdb_path

ROOT = Path(__file__).resolve().parents[1]
DEVDB = devdb_path("tiered")


@pytest.mark.parametrize("source_tile,reachable", [("X20Y8", False), ("X20Y9", True)])
def test_small_input_component_constrains_large_output_component(tmp_path, source_tile, reachable):
    binary = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not binary or not Path(binary).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the compiled nextpnr")

    def cell(bel, inputs, output):
        return dict(type="GENERIC_SLICE", attributes={"BEL": bel},
                    parameters={"K": "100", "INIT": "0" * 16 if inputs == ["x"] * 4 else "1010101010101010", "FF_USED": "0"},
                    port_directions={"I": "input", "F": "output", "Q": "output"},
                    connections={"I": inputs, "F": [output], "Q": []})

    document = {"modules": {"top": dict(attributes={"top": 1}, ports={}, cells={
        "driver": cell(source_tile + "_SLICE10", ["x"] * 4, 2),
        "sink": cell("X20Y9_SLICE14", [2, "x", "x", "x"], 3),
    }, netnames={"data": dict(bits=[2], attributes={}), "output": dict(bits=[3], attributes={})})}}
    source, placed = tmp_path / "source.json", tmp_path / "placed.json"
    source.write_text(json.dumps(document))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
    env.update(AGAMEMNON_DATA=str(ROOT / "agamemnon/chipdb"), AGAMEMNON_ROUTING_ADMISSION="tiered")
    result = subprocess.run([binary, "--uarch", "agrv2k", "-o", "chipdb=" + str(DEVDB),
                             "--json", str(source), "--write", str(placed), "--no-route"],
                            env=env, capture_output=True, text=True, timeout=45)
    log = result.stdout + result.stderr
    (tmp_path / "native.log").write_text(log)
    if reachable:
        assert result.returncode == 0, log
        assert placed.exists()
    else:
        assert result.returncode != 0, "placer accepted an unreachable cross-tile pair:\n" + log
        assert "local output topology cannot conduct net" in log, log
