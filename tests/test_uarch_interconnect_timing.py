"""Witnessed interconnect timing must reach nextpnr's routing APIs."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k"
SOURCE = UARCH / "agrv2k.cc"
PATCH = UARCH / "nextpnr-viaduct-timing.patch"


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_viaduct_patch_forwards_wire_and_pip_delay_hooks_with_fallbacks():
    patch = PATCH.read_text(encoding="utf-8")
    assert "uarch->getWireDelay(wire, delay)" in patch
    assert "uarch->getPipDelay(pip, delay)" in patch
    assert "return DelayQuad(0);" in patch
    assert "return DelayQuad(pip_info(pip).delay);" in patch

    build = (UARCH / "build.sh").read_text(encoding="utf-8")
    assert 'TIMING_PATCH="$HERE/nextpnr-viaduct-timing.patch"' in build
    assert "apply --reverse --check" in build
    assert "apply --check" in build


def test_uarch_exposes_edge_lumped_delay_without_double_charging_wires():
    source = SOURCE.read_text(encoding="utf-8")
    wire_delay = _between(
        source,
        "bool getWireDelay(WireId wire, DelayQuad &delay) const override",
        "bool getPipDelay(PipId pip, DelayQuad &delay) const override",
    )
    pip_delay = _between(
        source,
        "bool getPipDelay(PipId pip, DelayQuad &delay) const override",
        "void init(Context *ctx) override",
    )
    assert "double-count" in wire_delay
    assert "getDelayFromNS(0.0)" in wire_delay
    assert "pip_delay_by_index.find(pip.index)" in pip_delay
    assert "DelayQuad(found->second)" in pip_delay


def test_lookahead_uses_only_admitted_timed_graph_edges_not_hpwl():
    source = SOURCE.read_text(encoding="utf-8")
    estimate = _between(
        source,
        "delay_t estimateDelay(WireId src, WireId dst) const override",
        "delay_t predictDelay(BelId src_bel",
    )
    graph_build = _between(source, 'Csv c(path("dev_pips.csv"))', "// Build the placer's")

    assert "timing_distances_to(destination)" in estimate
    assert "args.delayScale" not in estimate
    assert "abs(" not in estimate
    assert "getDelayFromNS(0.0)" in estimate
    assert "timing_uphill.at(destination_node)" in graph_build
    assert "pip_delay < old_delay->second" in graph_build


def test_uarch_consumes_the_generator_witness_column_without_a_formula():
    source = SOURCE.read_text(encoding="utf-8")
    pip_load = _between(source, 'Csv c(path("dev_pips.csv"))', "// Build the placer's")
    routing = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(
        encoding="utf-8"
    )
    measured = json.loads(
        (ROOT / "agamemnon" / "chipdb" / "wire_timing_measured.json").read_text(
            encoding="utf-8"
        )
    )

    assert "ctx->getDelayFromNS(to_double(c.at(4), 0.05))" in pip_load
    assert "pip_delay_by_index[pip.index] = pip_delay" in pip_load
    assert "base_ns = wire_timing.select_routing_delay_ns(" in routing
    assert "if family in _wt_measured:" in routing
    assert measured["families_ns"] == {
        "RMUX": 0.336,
        "ClkMUX": 0.133,
        "BufMUX": 0.534,
    }
