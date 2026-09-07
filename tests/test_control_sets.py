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
