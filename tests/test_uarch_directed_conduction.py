"""Regression guards for directed placement use of the admitted routing graph."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_condplace_preserves_producer_to_consumer_direction():
    source = UARCH.read_text(encoding="utf-8")
    condplace = _between(source, "static void pack_condplace", "static void pack_dense")

    assert "tile_adj.find(source)" in condplace
    assert "it->second.count(sink)" in condplace
    assert "tile_adj.find(sink)" not in condplace
    assert "tile_pred[sink].insert(edge.first)" in condplace
    assert "conduct(t, assign[nb]) ? 1000" in condplace
    assert "conduct(assign[nb], t) ? 1000" in condplace
    assert "tile_pred.find(assign[d])" in condplace
    assert "tile_adj.find(assign[dr])" in condplace


def test_regional_candidate_selection_does_not_symmetrize_the_rrg():
    source = UARCH.read_text(encoding="utf-8")
    condplace = _between(source, "static void pack_condplace", "static void pack_dense")

    assert "std::vector<int> region = cand" in condplace
    assert "und[kv.first]" not in condplace
    assert "und[n]" not in condplace


def test_condpair_and_k_hop_closure_are_directed():
    source = UARCH.read_text(encoding="utf-8")
    tiles = _between(source, "bool tiles_conduct", "const std::unordered_set<int> &reachable_from")
    closure = _between(source, "// Precompute the K-hop conducting closure", "// Lock an explicitly requested")
    legality = _between(source, "// CONDUCTING-PAIR:", "return true;\n    }\n};")

    assert "tile_reach.find(source)" in tiles
    assert "tile_adj.find(source)" in tiles
    assert "tile_reach.find(sink)" not in tiles
    assert "tile_adj.find(sink)" not in tiles

    assert "auto it = tile_adj.find(x)" in closure
    assert "nodes.insert(kv.second.begin(), kv.second.end())" in closure
    assert "u[b].insert" not in closure

    assert "tiles_conduct(driver_loc.x, driver_loc.y, loc.x, loc.y)" in legality
    assert "tiles_conduct(loc.x, loc.y, user_loc.x, user_loc.y)" in legality
