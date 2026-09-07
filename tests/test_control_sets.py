import pytest

from agamemnon.engine import control_sets


def test_registers_sharing_every_control_form_one_set():
    report = control_sets.control_sets([
        {"clock": "clk", "enable": "en", "sync": "rst", "async": None},
        {"clock": "clk", "enable": "en", "sync": "rst", "async": None},
    ])

    assert report.registers == 2
    assert report.distinct_sets == 1
    assert report.demand() == {"clock": 1, "enable": 1, "sync": 1, "async": 0}


def test_differing_enables_split_the_sets_but_share_the_sync_line():
    report = control_sets.control_sets([
        {"clock": "clk", "enable": "a", "sync": "rst"},
        {"clock": "clk", "enable": "b", "sync": "rst"},
    ])

    assert report.distinct_sets == 2
    assert report.demand()["enable"] == 2
    assert report.demand()["sync"] == 1


def test_constant_tieoffs_do_not_consume_a_line():
    report = control_sets.control_sets([
        {"clock": "clk", "enable": "1'h1", "sync": "1'h0", "async": "1'h1"},
        {"clock": "clk", "enable": "vcc", "sync": "gnd", "async": "0"},
    ])

    assert report.demand() == {"clock": 1, "enable": 0, "sync": 0, "async": 0}
    assert report.distinct_sets == 1        # both collapse to the same set
    assert report.fits_budget()


def test_budget_is_two_lines_per_family():
    assert control_sets.TILE_CONTROL_BUDGET == {
        "clock": 2, "async": 2, "sync": 2, "enable": 2}


def test_three_enables_exceed_the_per_tile_budget():
    report = control_sets.control_sets(
        [{"clock": "clk", "enable": e} for e in ("a", "b", "c")])

    assert not report.fits_budget()
    assert report.over_budget()["enable"] == (3, 2)


def test_the_vendor_shaped_control_profile_fits():
    """One clock, one sync reset, no async, a handful of enables."""
    registers = (
        [{"clock": "clock", "enable": "write_pending", "sync": "reset_commit", "async": "1'h1"}] * 32
        + [{"clock": "clock", "enable": "syn__002_", "sync": "reset_commit", "async": "1'h1"}] * 22
        + [{"clock": "clock", "enable": "1'h1", "sync": "reset_commit", "async": "1'h1"}] * 3
    )
    report = control_sets.control_sets(registers)

    assert report.registers == 57
    assert report.distinct_sets == 3
    assert report.demand()["clock"] == 1
    assert report.demand()["sync"] == 1     # the shared reset needs ONE line
    assert report.demand()["async"] == 0
    assert report.demand()["enable"] == 2
    assert report.fits_budget()


def test_extraction_from_a_document_identifies_registers_by_clock_port():
    doc = {"modules": {"top": {
        "cells": {
            "ff": {"type": "DFF", "connections": {"CLK": [3], "EN": [4], "D": [5], "Q": [6]}},
            "lut": {"type": "LUT", "connections": {"I": [5], "F": [7]}},
        },
        "netnames": {"clk": {"bits": [3]}, "en": {"bits": [4]}},
    }}}
    report = control_sets.control_sets_from_document(doc)

    assert report.registers == 1            # the LUT is not a register
    assert report.demand()["clock"] == 1
    assert report.demand()["enable"] == 1


def test_extraction_treats_literal_tieoffs_as_constants():
    doc = {"modules": {"top": {
        "cells": {"ff": {"type": "DFF", "connections": {"CLK": [3], "EN": ["1"]}}},
        "netnames": {"clk": {"bits": [3]}},
    }}}
    report = control_sets.control_sets_from_document(doc)

    assert report.demand()["enable"] == 0


def test_report_serialises_with_schema_and_orders_sets_by_size():
    report = control_sets.control_sets(
        [{"clock": "c", "enable": "big"}] * 5 + [{"clock": "c", "enable": "small"}])
    payload = report.as_dict()

    assert payload["schema"] == control_sets.CONTROL_SET_SCHEMA
    assert payload["sets"][0]["registers"] == 5
    assert payload["fits_tile_budget"] is True


def test_format_report_marks_the_over_budget_family():
    report = control_sets.control_sets(
        [{"clock": "clk", "enable": e} for e in ("a", "b", "c")])
    text = control_sets.format_report(report)

    assert "OVER" in text
    assert "fits per-tile budget : no" in text


def test_document_without_modules_is_rejected():
    with pytest.raises(ValueError):
        control_sets.control_sets_from_document({"modules": {}})


def test_bind_tile_lines_gives_each_signal_its_own_line():
    bound = control_sets.bind_tile_lines([
        {"tile": (14, 8), "clock": "clk", "enable": "a"},
        {"tile": (14, 8), "clock": "clk", "enable": "b"},
    ])

    assert set(bound[((14, 8), "enable")].values()) == {0, 1}
    assert bound[((14, 8), "clock")] == {"clk": 1}


def test_bind_tile_lines_reuses_one_line_for_a_shared_signal():
    bound = control_sets.bind_tile_lines(
        [{"tile": (1, 1), "clock": "clk", "sync": "rst"}] * 5)

    assert bound[((1, 1), "sync")] == {"rst": 1}


def test_bind_tile_lines_skips_constant_tieoffs():
    bound = control_sets.bind_tile_lines([
        {"tile": (2, 2), "clock": "clk", "enable": "1'h1", "async": "1'h1"}])

    assert ((2, 2), "enable") not in bound
    assert ((2, 2), "async") not in bound


def test_bind_tile_lines_refuses_an_over_budget_tile_by_name():
    with pytest.raises(control_sets.ControlBindingError) as excinfo:
        control_sets.bind_tile_lines([
            {"tile": (9, 9), "clock": "clk", "enable": e} for e in ("a", "b", "c")])

    message = str(excinfo.value)
    assert "(9, 9)" in message and "enable" in message and "a, b, c" in message


def test_partition_keeps_every_group_within_the_budget():
    registers = [{"clock": "clk", "enable": e}
                 for e in ("a", "a", "b", "b", "c", "c", "d", "d")]
    groups = control_sets.partition_by_control_set(registers, capacity=16)

    for group in groups:
        enables = {r["enable"] for r in group}
        assert len(enables) <= control_sets.TILE_CONTROL_BUDGET["enable"]
    assert sum(len(g) for g in groups) == len(registers)


def test_partition_respects_tile_capacity():
    registers = [{"clock": "clk", "enable": "same"} for _ in range(20)]
    groups = control_sets.partition_by_control_set(registers, capacity=16)

    assert [len(g) for g in groups] == [16, 4]


def test_partition_co_locates_registers_that_share_a_control_set():
    """The whole point: same-enable registers land together, off general routing."""
    registers = ([{"clock": "clk", "enable": "x"}] * 6
                 + [{"clock": "clk", "enable": "y"}] * 6)
    groups = control_sets.partition_by_control_set(registers, capacity=16)

    assert len(groups) == 1                      # both fit: 2 enables, budget 2
    assert len(groups[0]) == 12


def test_partition_opens_a_new_tile_for_a_third_control_set():
    registers = [{"clock": "clk", "enable": e} for e in ("x", "y", "z")]
    groups = control_sets.partition_by_control_set(registers, capacity=16)

    assert len(groups) == 2
    assert {r["enable"] for r in groups[0]} == {"x", "y"}
    assert {r["enable"] for r in groups[1]} == {"z"}
