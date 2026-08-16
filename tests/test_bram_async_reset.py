"""The proven Port-A reset route is a real scalar BRAM input.

The configuration parameters PORTA_RSTIN_EN/PORTA_RSTOUT_EN only open gates;
they cannot replace the routed AsyncReset0 signal.  The vendor-positive
same-Port-A write oracle uses MCU_RESETN through TileAsyncMUX00, so keep that
input present and scalar at every layer of the open flow.
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def test_bram_primitive_exposes_async_reset_separately_from_gate_parameters():
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert "input AsyncReset0" in prims
    assert "parameter PORTA_RSTIN_EN" in prims
    assert "parameter PORTA_RSTOUT_EN" in prims


def test_bram_bel_maps_async_reset_to_the_measured_terminal():
    with (CHIPDB / "bram9k_bel.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r for r in rows if r["port"] == "AsyncReset0"] == [{
        "port": "AsyncReset0",
        "bit": "0",
        "x": "13",
        "y": "4",
        "res": "TileAsyncMUX00",
    }]


def test_arch_emits_async_reset_as_a_scalar_bel_pin():
    source = (ROOT / "agamemnon" / "engine" / "features" / "bram.py").read_text(
        encoding="utf-8"
    )
    assert '"AsyncReset0",' in source
    assert 'pin = port if port in _BRAM_SCALAR else "%s[%d]" % (port, bit)' in source
    assert '"AsyncReset0[0]"' not in source


def test_measured_reset_route_and_selector_codeword_remain_present():
    with (CHIPDB / "bram9k_edges.csv").open(newline="") as handle:
        edges = list(csv.DictReader(handle))
    assert any(
        r["src_res"] == "IMUX32" and r["dst_res"] == "TileAsyncMUX00"
        and r["src_x"] == r["dst_x"] == "13"
        and r["src_y"] == r["dst_y"] == "4"
        for r in edges
    )

    resolver = json.loads((CHIPDB / "bram_resolver.json").read_text(encoding="utf-8"))
    assert resolver["L0"]["TileAsyncMUX|0|IMUX|32|0|0"] == [2, 3, 7]


def test_measured_reset_codeword_clears_the_inherited_default():
    with (CHIPDB / "bram_route_codewords.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(r for r in rows if r["dst_family"] == "TileAsyncMUX")
    assert (
        row["dst_family"], row["dst_index"], row["src_family"], row["src_index"],
        row["ddx"], row["ddy"], row["config"],
    ) == ("TileAsyncMUX", "0", "IMUX", "32", "0", "0", "CFG_TileAsyncMUX")
    assert row["clear_selections"] == "0;1;2;3;4;5;6;7"
    assert row["set_selections"] == "2;7"


def test_exact_reset_codeword_replaces_the_rom_blob_default():
    from agamemnon.engine.features import bram as bram_feature

    state = bram_feature.BramState()
    field = {
        (13, 4, "CFG_TileAsyncMUX", sel): (100, 1 << sel)
        for sel in range(8)
    }
    state.sets = [field[(13, 4, "CFG_TileAsyncMUX", 3)], (200, 1)]
    state.exact_codewords = {
        ("TileAsyncMUX", 0, "IMUX", 32, 0, 0): (
            "CFG_TileAsyncMUX", list(range(8)), [2, 7],
        )
    }
    route_sets, route_clears = [], []
    assert bram_feature.FEATURE.resolve_route(
        state,
        (13, 4, "IMUX", 32), (13, 4, "TileAsyncMUX", 0),
        field, {"TileAsyncMUX": 1}, route_sets, route_clears=route_clears,
    )
    assert state.sets == [(200, 1)]
    assert route_clears == [field[(13, 4, "CFG_TileAsyncMUX", sel)] for sel in range(8)]
    assert route_sets == [
        field[(13, 4, "CFG_TileAsyncMUX", 2)],
        field[(13, 4, "CFG_TileAsyncMUX", 7)],
    ]

