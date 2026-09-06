"""Complete physical selector ownership for the admitted multi-site routes."""
import csv
from dataclasses import replace
from pathlib import Path

import pytest

from agamemnon.engine.bram_routing import FIELDS, TABLE, endpoint, load_routes
from agamemnon.engine.features.bram import BramFeature, BramState
from agamemnon.engine.features.routing import RoutingFeature

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon/chipdb"
ROUTES = load_routes(CHIPDB)


@pytest.fixture(scope="module")
def cells():
    cells, _ = RoutingFeature.load_cell_map(CHIPDB)
    with (CHIPDB / "bram_cell.csv").open(newline="") as stream:
        cells.update({(int(r["x"]), int(r["y"]), r["mux"], int(r["sel"])):
                      (int(r["byte"]), int(r["mask"])) for r in csv.DictReader(stream)})
    return cells


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.source + "." + r.destination)
def test_complete_selector_replaces_stale_bits_without_touching_neighbors(route, cells):
    source, destination = endpoint(route.source), endpoint(route.destination)
    x, y, _, _ = destination
    field = {cells[x, y, route.config, s] for s in route.clear}
    expected = {cells[x, y, route.config, s] for s in route.set_bits}
    neighbor = (999999, 1)
    state = BramState(site_codewords={(source, destination): route}, sets=list(field) + [neighbor])
    sets, clears = [], []
    assert BramFeature().resolve_route(state, source, destination, cells, {}, sets, clears)
    assert set(clears) == field and set(sets) == expected
    assert state.sets == [neighbor]
    before = (list(sets), list(clears), list(state.sets), dict(state.control_owners))
    other = (99, 99, "RMUX", 0)
    state.site_codewords[other, destination] = replace(route, source="X99Y99_RMUX00")
    with pytest.raises(SystemExit, match="conflicting BRAM selector sources"):
        BramFeature().resolve_route(state, other, destination, cells, {}, sets, clears)
    assert (sets, clears, state.sets, state.control_owners) == before


def test_missing_physical_cell_rejects_before_owning_or_mutating(cells):
    cells = dict(cells)
    route = ROUTES[0]
    source, destination = endpoint(route.source), endpoint(route.destination)
    x, y, _, _ = destination
    cells.pop((x, y, route.config, route.clear[0]))
    state = BramState(site_codewords={(source, destination): route}, sets=[(999999, 1)])
    sets, clears = [], []
    with pytest.raises(SystemExit, match="incomplete physical selector cells"):
        BramFeature().resolve_route(state, source, destination, cells, {}, sets, clears)
    assert not state.control_owners and not sets and not clears
    assert state.sets == [(999999, 1)]


def test_distinct_sources_have_distinct_complete_codewords():
    owners = {}
    for route in ROUTES:
        key = (route.destination, route.config, frozenset(route.set_bits))
        assert key not in owners or owners[key] == route.source
        owners[key] = route.source


def test_ambiguous_selector_authority_rejects(tmp_path):
    with (CHIPDB / TABLE).open(newline="") as stream:
        row = next(csv.DictReader(stream))
    alias = dict(row, src_wire="X13Y3_RMUX99")
    assert alias["src_wire"] != row["src_wire"]
    with (tmp_path / TABLE).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows([row, alias])
    with pytest.raises(ValueError, match="share a selector codeword"):
        load_routes(tmp_path)


@pytest.mark.parametrize("column,value,diagnostic", [
    ("clear_selectors", "0", "complete destination field"),
    ("set_selectors", "999", "outside its selector field"),
    ("pip_type", "UNVERIFIED", "clock classification"),
    ("evidence", "", "unbound BRAM selector field"),
])
def test_malformed_route_authority_rejects(tmp_path, column, value, diagnostic):
    with (CHIPDB / TABLE).open(newline="") as stream:
        row = next(csv.DictReader(stream))
    row[column] = value
    with (tmp_path / TABLE).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError, match=diagnostic):
        load_routes(tmp_path)
