"""Native clock closure must bind each placed BRAM's own branch."""
import json

import pytest

from test_uarch_typed_gclk0 import _bram, _netlist, _run, _source


@pytest.mark.parametrize("sites", [(3,), (4,), (3, 4)])
def test_native_bram_site_clock_tree(tmp_path, sites):
    cells = {"clock_source": _source("MCU_BUS_CLOCK", 2)}
    for y in sites:
        memory = _bram(2)
        memory["attributes"]["NEXTPNR_BEL"] = f"X13Y{y}_BRAM"
        cells[f"memory{y}"] = memory
    result, output = _run(tmp_path, "multisite_clock", _netlist(cells, {"clock": 2}),
                          "--router", "router2")
    assert result.returncode == 0, result.stdout + result.stderr
    route = json.loads(output.read_text())["modules"]["top"]["netnames"]["clock"]["attributes"]["ROUTING"]
    assert "GCLK0.X13Y0_BufMUX05" in route
    for y in (3, 4):
        for edge in (f"X13Y0_BufMUX05.X13Y{y}_SeamMUX01",
                     f"X13Y{y}_SeamMUX01.X13Y{y}_TileClkMUX01"):
            assert (edge in route) == (y in sites)
    assert f"atomically bound {1 + 2 * len(sites)} typed GCLK0 tree PIP(s)" in result.stdout + result.stderr


@pytest.mark.parametrize("site", [1, 2])
def test_native_unmodeled_clock_site_rejects(tmp_path, site):
    memory = _bram(2)
    memory["attributes"]["NEXTPNR_BEL"] = f"X13Y{site}_BRAM"
    document = _netlist({"clock_source": _source("MCU_BUS_CLOCK", 2), "memory": memory}, {"clock": 2})
    result, output = _run(tmp_path, "unmodeled_clock_site", document, "--router", "router2")
    assert result.returncode != 0 and not output.exists()
    assert f"clock topology has no admitted branch for X13Y{site}_BRAM" in result.stdout + result.stderr
