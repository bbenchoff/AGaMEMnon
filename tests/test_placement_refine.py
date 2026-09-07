import pytest

from agamemnon.engine import placement_refine


def _document(cells, netnames):
    return {"modules": {"top": {"cells": cells, "netnames": netnames}}}


def _cell(bel, connections, cell_type="GENERIC_SLICE", strength=1, attrs=None):
    attributes = {"BEL_STRENGTH": strength}
    if bel:
        attributes["NEXTPNR_BEL"] = bel
    attributes.update(attrs or {})
    return {"type": cell_type, "attributes": attributes, "connections": connections}


def test_two_connected_cells_are_pulled_onto_one_tile():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X5Y5_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    placement, result = placement_refine.refine(doc)

    assert result.span_before == 2
    assert result.span_after == 1
    assert result.moves == 1
    assert placement["a"] == placement["b"]


def test_an_already_local_placement_is_left_alone():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X1Y1_SLICE2", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    _, result = placement_refine.refine(doc)

    assert result.moves == 0
    assert result.span_before == result.span_after == 1


def test_locked_cells_are_never_moved():
    doc = _document(
        cells={
            "anchor": _cell("X9Y9_SLICE0", {"F": [10]}, strength=5),
            "b": _cell("X1Y1_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    placement, result = placement_refine.refine(doc)

    assert placement["anchor"] == (9, 9)      # unmoved
    assert placement["b"] == (9, 9)           # the movable one relocated instead
    assert result.movable_cells == 1


def test_mcu_typed_cells_are_fixed():
    doc = _document(
        cells={
            "m": _cell("X10Y5_SLICE0", {"DOUT": [10]}, cell_type="MCU_DOUT"),
            "b": _cell("X1Y1_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    placement, result = placement_refine.refine(doc)

    assert placement["m"] == (10, 5)
    assert result.movable_cells == 1


def test_pinpacked_and_cluster_cells_are_fixed():
    for attr in ("AGRV2K_BRAM_PINPACKED", "AGRV2K_ROUTE_THROUGH", "NEXTPNR_CLUSTER"):
        doc = _document(
            cells={
                "p": _cell("X7Y7_SLICE0", {"F": [10]}, attrs={attr: 1}),
                "b": _cell("X1Y1_SLICE0", {"I0": [10]}),
            },
            netnames={"n": {"bits": [10]}},
        )
        placement, result = placement_refine.refine(doc)
        assert placement["p"] == (7, 7), attr
        assert result.movable_cells == 1, attr


def test_tile_capacity_is_respected():
    # Four cells all want tile (1,1); capacity 2 means only one can join the anchor.
    cells = {"anchor": _cell("X1Y1_SLICE0", {"F": [10]}, strength=5)}
    cells["occupant"] = _cell("X1Y1_SLICE2", {"I0": [11]}, strength=5)
    for i, name in enumerate(("x", "y")):
        cells[name] = _cell("X6Y6_SLICE%d" % (i * 2), {"I0": [10]})
    doc = _document(cells, netnames={"n": {"bits": [10]}, "other": {"bits": [11]}})

    placement, _ = placement_refine.refine(doc, tile_capacity=2)

    assert sum(1 for t in placement.values() if t == (1, 1)) == 2  # cap not exceeded


def test_a_move_that_does_not_reduce_total_span_is_rejected():
    # 'mid' is connected to two cells on different tiles; moving it to either
    # keeps total span at 3, so no strictly-improving move exists.
    doc = _document(
        cells={
            "l": _cell("X1Y1_SLICE0", {"F": [10]}, strength=5),
            "mid": _cell("X3Y1_SLICE0", {"I0": [10], "F": [11]}),
            "r": _cell("X5Y1_SLICE0", {"I0": [11]}, strength=5),
        },
        netnames={"a": {"bits": [10]}, "b": {"bits": [11]}},
    )
    _, result = placement_refine.refine(doc)

    assert result.span_before == 4
    assert result.span_after == 3   # mid joins one side, the other net still spans 2
    assert result.moves == 1


def test_refinement_is_deterministic():
    def build():
        return _document(
            cells={
                "a": _cell("X1Y1_SLICE0", {"F": [10]}),
                "b": _cell("X4Y4_SLICE0", {"I0": [10], "F": [11]}),
                "c": _cell("X8Y8_SLICE0", {"I0": [11]}),
            },
            netnames={"n": {"bits": [10]}, "m": {"bits": [11]}},
        )

    first, r1 = placement_refine.refine(build())
    second, r2 = placement_refine.refine(build())

    assert first == second
    assert r1.as_dict() == r2.as_dict()


def test_result_serialises_with_schema():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X5Y5_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    payload = placement_refine.refine(doc)[1].as_dict()

    assert payload["schema"] == placement_refine.REFINE_SCHEMA
    assert payload["span_reduction"] == pytest.approx(0.5)


def test_locality_after_refine_reports_both_sides_comparably():
    doc = _document(
        cells={
            "a": _cell("X1Y1_SLICE0", {"F": [10]}),
            "b": _cell("X5Y5_SLICE0", {"I0": [10]}),
        },
        netnames={"n": {"bits": [10]}},
    )
    before, after, result = placement_refine.locality_after_refine(doc)

    assert before.mean_span == 2.0
    assert after.mean_span == 1.0
    assert after.intra_tile_fraction == 1.0
    assert result.moves == 1


def test_document_without_modules_is_rejected():
    with pytest.raises(ValueError):
        placement_refine.refine({"modules": {}})
