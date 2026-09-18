"""Actual routing of movable, shared constant trees on an invented graph."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from agamemnon.engine.router2_probe import _reservation_fixture_json


@pytest.mark.parametrize("seed", [1, 2, 7])
@pytest.mark.parametrize("preroute_constant", [False, True])
def test_constant_tree_releases_the_signals_only_corridor(tmp_path, seed, preroute_constant):
    binary = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not binary or not Path(binary).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the compiled nextpnr")
    source = tmp_path / "probe.json"
    routed = tmp_path / "routed.json"
    source.write_text(_reservation_fixture_json(), encoding="utf-8")
    command = [binary, "--uarch", "agamemnon_router2_probe", "--json", str(source),
               "--write", str(routed), "--router", "router2", "--seed", str(seed)]
    if preroute_constant:
        command += ["-o", "ripup=1"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    log = result.stdout + result.stderr
    assert result.returncode == 0, log[-4000:]
    assert "Routing complete" in log
    if preroute_constant:
        # Older binaries ignore unknown -o keys; they must not pass this test
        # by silently running only the original reservation fixture.
        assert "seed movable constant tree through CHOKE" in log
    nets = json.loads(routed.read_text(encoding="utf-8"))["modules"]["top"]["netnames"]
    signal = nets["SIG"]["attributes"]["ROUTING"]
    constant = nets["$PACKER_GND_NET"]["attributes"]["ROUTING"]
    assert "CHOKE" in signal
    assert "LOCAL_GND" in constant
    assert "CHOKE" not in constant
    for index in range(4):
        assert "WIDE_IN%d" % index in constant
