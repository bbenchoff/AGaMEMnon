import json

import pytest

from agamemnon.engine import placement_locality


def _document(cells, netnames):
    """Build a minimal nextpnr-shaped document."""
    return {"modules": {"top": {"cells": cells, "netnames": netnames}}}


def _cell(bel, connections):
    return {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": bel} if bel else {},
        "connections": connections,
    }


def test_net_confined_to_one_tile_is_intra_tile():
    doc = _document(
        cells={
            "a": _cell("X3Y4_SLICE0", {"F": [10]}),
            "b": _cell("X3Y4_SLICE2", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.placed_cells == 2
    assert report.occupied_tiles == 1
    assert report.nets == 1
    assert report.intra_tile_nets == 1
    assert report.mean_span == 1.0


def test_net_crossing_tiles_counts_every_distinct_tile():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X2Y1_SLICE0", {"I0": [10]}),
            "c": _cell("X9Y7_SLICE4", {"I1": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.nets == 1
    assert report.intra_tile_nets == 0
    assert report.span_histogram == {3: 1}
    assert report.mean_span == 3.0


def test_two_cells_in_the_same_tile_do_not_inflate_the_span():
    """Span counts distinct tiles, not endpoints -- three sinks in one tile is span 1."""
    doc = _document(
        cells={
            "a": _cell("X5Y5_SLICE0", {"F": [7]}),
            "b": _cell("X5Y5_SLICE2", {"I0": [7]}),
            "c": _cell("X5Y5_SLICE4", {"I1": [7]}),
        },
        netnames={"n": {"bits": [7]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.span_histogram == {1: 1}
    assert report.intra_tile_fraction == 1.0


def test_constant_and_global_nets_are_ignored():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10], "I0": [1]}),
            "b": _cell("X8Y8_SLICE0", {"I0": [10], "I1": [1]}),
        },
        netnames={"n": {"bits": [10]}, "vcc": {"bits": [1]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.nets == 1  # vcc excluded despite spanning both tiles
    assert report.span_histogram == {2: 1}


def test_unplaced_cells_are_skipped():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell(None, {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.placed_cells == 1
    assert report.span_histogram == {1: 1}


def test_cells_per_tile_and_fraction_on_a_mixed_design():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X1Y1_SLICE2", {"I0": [10], "F": [11]}),
            "c": _cell("X4Y1_SLICE0", {"I0": [11]}),
        },
        netnames={"local": {"bits": [10]}, "crossing": {"bits": [11]}},
    )
    report = placement_locality.net_locality(doc)

    assert report.placed_cells == 3
    assert report.occupied_tiles == 2
    assert report.cells_per_tile == pytest.approx(1.5)
    assert report.nets == 2
    assert report.intra_tile_nets == 1
    assert report.intra_tile_fraction == pytest.approx(0.5)
    assert report.mean_span == pytest.approx(1.5)


def test_report_serialises_with_schema_and_round_trips():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X2Y2_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    payload = placement_locality.net_locality(doc).as_dict()

    assert payload["schema"] == placement_locality.LOCALITY_SCHEMA
    assert payload["span_histogram"] == {"2": 1}
    assert json.loads(json.dumps(payload)) == payload


def test_format_report_reports_the_span_line():
    doc = _document(
        cells={"a": _cell("X1Y1_SLICE0", {"F": [10]})},
        netnames={"n": {"bits": [10]}},
    )
    text = placement_locality.format_report(placement_locality.net_locality(doc))

    assert "mean net span" in text
    assert "intra-tile nets" in text


def test_document_without_modules_is_rejected():
    with pytest.raises(ValueError):
        placement_locality.net_locality({"modules": {}})


def test_empty_design_does_not_divide_by_zero():
    report = placement_locality.net_locality(_document(cells={}, netnames={}))

    assert report.mean_span == 0.0
    assert report.cells_per_tile == 0.0
    assert report.intra_tile_fraction == 0.0
