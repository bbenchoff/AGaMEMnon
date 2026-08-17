from pathlib import Path

import pytest

from agamemnon.engine.route_through import (
    FEATURE,
    RouteThroughPolicyError,
    complete_footprint_for_cell,
    load_footprints,
)
from agamemnon.engine.features.core_logic import CoreLogicFeature
from agamemnon.engine.features.routing import RoutingFeature, RoutingState
from agamemnon.engine.registry import CONSTANTS, options_from


ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "agamemnon" / "chipdb" / "route_through_footprints.csv"


def test_uarch_admits_only_the_four_characterized_route_through_sites():
    uarch = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" /
             "agrv2k.cc").read_text(encoding="utf-8")
    assert 'ctx->id("AGRV2K_ROUTE_THROUGH")' in uarch
    assert "loc.x == 14 && loc.y == 4 && (loc.z == 0 || loc.z == 5)" in uarch
    assert "loc.x == 14 && loc.y == 8 && loc.z == 8" in uarch
    assert "loc.x == 14 && loc.y == 7 && loc.z == 3" in uarch
    assert "route_through_cell && !route_through_site" in uarch
    assert "void lock_route_through_inputs()" in uarch
    assert "lock_route_through_inputs();" in uarch
    assert "static void pack_route_through_bels(Context *ctx)" in uarch
    assert "static void pack_distribution_root_bels(Context *ctx)" in uarch
    assert 'requested->second.as_string() != "X17Y12_SLICE0"' in uarch
    assert uarch.index("pack_distribution_root_bels(ctx);") < uarch.index("pack_route_through_bels(ctx);")
    assert uarch.index("pack_route_through_bels(ctx);") < uarch.index("pack_entry_buffers();")
    for edge in (
        "X14Y4_RMUX22.X14Y4_IMUX20",
        "X15Y8_RMUX00.X14Y8_IMUX32",
        "X14Y4_RMUX71.X14Y4_IMUX03",
        "X14Y7_RMUX47.X14Y7_IMUX15",
    ):
        assert edge in uarch


def _cell(site="X14Y4_SLICE5", init="1010101010101010", ff_used="0", requested=None):
    attributes = {"NEXTPNR_BEL": site}
    if requested is not None:
        attributes["AGRV2K_ROUTE_THROUGH"] = requested
    return {
        "type": "GENERIC_SLICE",
        "attributes": attributes,
        "parameters": {"INIT": init, "FF_USED": ff_used},
        "connections": {"I": [17]},
    }


def _nets(edge="X14Y4_RMUX22.X14Y4_IMUX20"):
    return [("identity", {17}, "other.edge;%s" % edge)]


def test_extracted_table_is_four_disjoint_complete_footprints():
    footprints = load_footprints(TABLE)
    assert set(footprints) == {(14, 4, 0), (14, 4, 5), (14, 7, 3), (14, 8, 8)}
    assert [len(footprints[site]) for site in sorted(footprints)] == [8, 6, 4, 7]
    assert len({entry["byte"] for entries in footprints.values() for entry in entries}) == 25
    assert {entry["sparse_policy"] for entry in footprints[(14, 8, 8)]} == {"fail_closed"}
    assert {entry["sparse_policy"] for entry in footprints[(14, 4, 5)]} == {"allow"}


def test_exact_identity_and_final_edge_select_complete_footprint_automatically():
    footprints = load_footprints(TABLE)
    selected = complete_footprint_for_cell(_cell(), _nets(), footprints)
    assert [(entry["value"], entry["write_mask"]) for entry in selected] == [
        (120, 255), (120, 255), (2, 255), (0, 255), (64, 64), (68, 68)
    ]


def test_silicon_minimized_readback_terminal_masks_are_site_bounded():
    footprints = load_footprints(TABLE)
    left = footprints[(14, 4, 5)][4:]
    right = footprints[(14, 8, 8)][4:]
    assert [(entry["byte"], entry["value"], entry["write_mask"]) for entry in left] == [
        (68521, 0x40, 0x40), (71190, 0x44, 0x44)
    ]
    assert [(entry["byte"], entry["value"], entry["write_mask"]) for entry in right] == [
        (38825, 0x40, 0x40), (36855, 0x08, 0x08), (36971, 0x02, 0x02)
    ]


def test_working_x9_vendor_i3_route_through_is_exact_and_zero_coded():
    footprints = load_footprints(TABLE)
    selected = complete_footprint_for_cell(
        _cell(site="X14Y4_SLICE0", init="1111111100000000", requested="1"),
        _nets("X14Y4_RMUX71.X14Y4_IMUX03"),
        footprints,
    )
    assert {entry["init"] for entry in selected} == {0xFF00}
    assert [(entry["byte"], entry["value"], entry["write_mask"]) for entry in selected] == [
        (65852, 0x78, 0xFF), (65968, 0x78, 0xFF), (66084, 0x01, 0xFF),
        (66200, 0, 0xFF), (65853, 0, 0x02), (65969, 0, 0x08),
        (65855, 0x02, 0x02), (65971, 0x02, 0x02),
    ]


def test_explicit_route_through_has_exclusive_lut_ownership():
    feature = CoreLogicFeature()
    state = feature.prepare(
        {"cells": {"buffer": _cell(
            site="X14Y4_SLICE0", init="1111111100000000", requested="1"
        )}},
        selector_cells={},
        options=options_from({}),
        constants=CONSTANTS,
    )
    assert state.route_through_slices == {(14, 4, 0)}
    assert state.lut_sets == []
    assert feature.writable_bits(state) == set()


def test_route_through_mask_takes_selector_ownership_from_routing():
    state = RoutingState(sets=[(66084, 0x01), (66084, 0x04), (9, 0x08)])
    removed = RoutingFeature().delegate_bits(state, {(66084, 0x03)})
    assert removed == 1
    assert state.sets == [(66084, 0x04), (9, 0x08)]


def test_working_x9_haddr11_split_route_through_is_exact():
    footprints = load_footprints(TABLE)
    selected = complete_footprint_for_cell(
        _cell(site="X14Y7_SLICE3", init="1111111100000000", requested="1"),
        _nets("X14Y7_RMUX47.X14Y7_IMUX15"),
        footprints,
    )
    assert [(entry["byte"], entry["value"], entry["write_mask"]) for entry in selected] == [
        (43580, 0x78, 0xFF), (43696, 0x78, 0xFF),
        (43812, 0x04, 0xFF), (43928, 0, 0xFF),
    ]


def test_x9_data3_vendor_mcu_exit_codeword_is_bounded_and_exact():
    import csv

    table = ROOT / "agamemnon" / "chipdb" / "bram_x9_data3_mcu_exit.csv"
    with table.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["src_res"] == "RMUX03"
    assert rows[0]["edge_res"] == "BBMUXE05"
    assert rows[0]["sink_res"] == "SinkMUXPseudo05"
    assert rows[0]["selectors"] == "2;4"


@pytest.mark.parametrize(
    "cell,nets,message",
    [
        (_cell(site="X14Y4_SLICE4", requested="1"), _nets(), "no characterized"),
        (_cell(init="0", requested="1"), _nets(), "requires combinational INIT=0xAAAA"),
        (_cell(ff_used="1", requested="1"), _nets(), "requires combinational INIT=0xAAAA"),
        (_cell(requested="1"), _nets("wrong.edge"), "lacks characterized final edge"),
    ],
)
def test_explicit_route_through_requests_fail_closed(cell, nets, message):
    with pytest.raises(RouteThroughPolicyError, match=message):
        complete_footprint_for_cell(cell, nets, load_footprints(TABLE))


def test_unannotated_non_identity_does_not_change_emission():
    footprints = load_footprints(TABLE)
    assert complete_footprint_for_cell(_cell(init="0"), _nets(), footprints) == ()


def test_unannotated_identity_at_characterized_site_fails_closed_on_wrong_edge():
    with pytest.raises(RouteThroughPolicyError, match="sparse identity emission is unsafe"):
        complete_footprint_for_cell(
            _cell(site="X14Y8_SLICE8"),
            _nets("X14Y8_RMUX76.X14Y8_IMUX32"),
            load_footprints(TABLE),
        )


def test_unannotated_identity_at_unclassified_site_preserves_working_sparse_path():
    assert complete_footprint_for_cell(
        _cell(), _nets("X14Y4_RMUX40.X14Y4_IMUX20"), load_footprints(TABLE)
    ) == ()


def test_implicit_address_buffer_is_opt_in_and_exact(monkeypatch):
    module = {
        "cells": {},
        "netnames": {
            "address3": {
                "bits": [23],
                "attributes": {
                    "ROUTING": (
                        "X14Y8_RMUX71.X14Y8_IMUX39;"
                        "X14Y8_IMUX39.X14Y8_alta_slice09"
                    )
                },
            }
        },
    }
    monkeypatch.delenv("AGAMEMNON_BRAM_SITE_READ_PATHS", raising=False)
    assert FEATURE.prepare(module, ROOT / "agamemnon" / "chipdb").writes == []
    monkeypatch.setenv("AGAMEMNON_BRAM_SITE_READ_PATHS", "1")
    writes = FEATURE.prepare(module, ROOT / "agamemnon" / "chipdb").writes
    assert [(entry["byte"], entry["value"], entry["write_mask"]) for entry in writes] == [
        (38940, 0x78, 0xFF), (39056, 0x78, 0xFF),
        (39172, 0x01, 0xFF), (39288, 0x00, 0xFF),
    ]


def test_qualified_x18_bram_address_gnd_terminals_are_complete_exact_fields():
    import csv

    table = ROOT / "agamemnon" / "chipdb" / "bram_address_gnd_terminal_pip_cfg.csv"
    with table.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["src_wire"], row["dst_wire"]) for row in rows] == [
        ("X14Y4_RMUX54", "X13Y4_IMUX03"),
        ("X13Y4_RMUX28", "X13Y4_IMUX04"),
    ]
    assert rows[0]["clear_selectors"] == ";".join(str(i) for i in range(36, 48))
    assert rows[0]["set_selectors"] == "42;43;45"
    assert rows[1]["clear_selectors"] == ";".join(str(i) for i in range(12))
    assert rows[1]["set_selectors"] == "5;7;10;11"
