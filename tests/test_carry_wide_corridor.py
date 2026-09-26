"""Tests for the widened native short-same-tile carry corridor (2026-09-25).

Root cause: AGaMEMnon's carry validator/placer only ever admitted a chain
over 9 sites at the fixed X20Y12-downward corridor, so every counter/adder
wider than 9 sites (and, structurally, more than 9 sites in aggregate even
across independent chains) landed in the same corner tile regardless of
where the rest of the design placed. carry_qualified_sites.csv records the
tiles where a full 16-slice intra-tile CARRY pip run is silicon-witnessed
(tools/pipwit ledger, AG32-Docs, 2026-09-25); these tests pin that table's
shape and prove the corner tile is never the only legal root once a chain
exceeds 9 sites.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.carry_validate import (
    CarryValidationError,
    validate_routed_carry,
)

from test_carry_routed_validation import _module, _short  # noqa: E402  (reuse fixtures)


ROOT = Path(__file__).resolve().parents[1]
SITES_CSV = ROOT / "agamemnon" / "chipdb" / "carry_qualified_sites.csv"


def _load_sites():
    with SITES_CSV.open(newline="", encoding="utf-8") as stream:
        return {(int(row["x"]), int(row["y"])) for row in csv.DictReader(stream)}


def test_qualified_sites_table_pins_the_witness_export():
    sites = _load_sites()
    # Pinned to the 2026-09-25 tools/pipwit ledger export: 117 LogicTiles
    # whose full 15-pip intra-tile CARRY run is ring-witnessed. A change here
    # should come from re-running the ledger export, not from hand-editing.
    assert len(sites) == 117
    assert (20, 12) in sites  # the old corridor's root stays qualified


def test_corner_tile_is_not_the_only_qualified_site():
    sites = _load_sites()
    non_corner = sites - {(20, 12), (20, 11), (20, 10)}
    # 114 of 117 witnessed sites are away from the X20 corridor entirely;
    # X20Y12 is one legal root among many, never the sole option.
    assert len(non_corner) >= 100
    # Spread across the fabric, not clustered next to the corner.
    assert any(x <= 5 for x, _y in non_corner)
    assert any(x >= 15 and (x, _y) not in {(20, 12), (20, 11), (20, 10)}
               for x, _y in non_corner)


def test_wide_chain_validates_at_a_witnessed_non_corner_tile():
    sites = _load_sites()
    tile = next(iter(sites - {(20, 12), (20, 11), (20, 10)}))
    chain = _short(0, 12, tile[0], tile[1])  # 13 sites: seed + 12 members
    module = _module(chain)
    result = validate_routed_carry(module, wide_sites=sites, wide_cap=16)
    assert result.chains[0].profile == "short-same-tile"
    assert len(result.chains[0].sites) == 13


def test_wide_chain_at_an_unwitnessed_tile_is_refused():
    sites = _load_sites()
    unwitnessed = (14, 8)  # ring-witnessed 0/15 intra-tile CARRY pips
    assert unwitnessed not in sites
    chain = _short(0, 12, unwitnessed[0], unwitnessed[1])
    module = _module(chain)
    with pytest.raises(CarryValidationError, match="not a silicon-witnessed site"):
        validate_routed_carry(module, wide_sites=sites, wide_cap=16)


def test_short_chain_at_or_below_nine_sites_is_unrestricted_by_the_table():
    # The original <=9 checkpoint keeps its exact prior behaviour: no site
    # membership is required, matching main before this change.
    chain = _short(0, 8, 14, 8)  # 9 sites total, at an unwitnessed tile
    module = _module(chain)
    result = validate_routed_carry(module, wide_sites=frozenset(), wide_cap=16)
    assert result.chains[0].profile == "short-same-tile"


def test_kill_switch_reproduces_the_exact_previous_nine_site_cap():
    tile = next(iter(_load_sites() - {(20, 12), (20, 11), (20, 10)}))
    chain = _short(0, 12, tile[0], tile[1])  # 13 sites: legal under the wide cap
    module = _module(chain)
    # wide_cap=9 is the exact pre-widening default: a 13-site short-same-tile
    # chain can no longer exist at all (it must become one retained absolute
    # long-profile chain instead), regardless of the witnessed-site table.
    with pytest.raises(CarryValidationError):
        validate_routed_carry(module, wide_sites=_load_sites(), wide_cap=9)
    with pytest.raises(CarryValidationError):
        validate_routed_carry(module)  # defaults reproduce the same thing


def test_carry_feature_loads_the_same_table_carry_validate_uses():
    loaded = CARRY_FEATURE.load_qualified_sites(SITES_CSV.parent)
    assert loaded == _load_sites()


def test_carry_feature_prepare_defaults_to_wide_corridor_on(monkeypatch):
    monkeypatch.delenv("AGAMEMNON_CARRY_WIDE_CORRIDOR", raising=False)
    from agamemnon.engine.features.carry import carry_wide_corridor_enabled
    assert carry_wide_corridor_enabled() is True
    monkeypatch.setenv("AGAMEMNON_CARRY_WIDE_CORRIDOR", "0")
    assert carry_wide_corridor_enabled() is False
