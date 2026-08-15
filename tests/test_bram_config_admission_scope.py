"""Keep the BRAM config surface and the BRAM placement surface distinct.

Two different tables are easy to confuse, and confusing them produces a wrong
diagnosis in either direction:

* ``engine/pips_bram_pll.csv`` is the CONFIG surface. It carries decoded cells
  for all four BramTILEs X13Y1..Y4, so the 39 B4 configuration-encoding rows
  scope honestly to that range.
* ``chipdb/bram9k_bel.csv`` and ``chipdb/bram_cell.csv`` are the PLACEMENT and
  routing surface, and they hold X13Y4 only. One BRAM site can be placed and
  read; the other three cannot, whatever their config cells say.

The behavioural gap in the B4 rows is therefore not missing bits. It is that no
row has ever been exercised: every one is ``silicon: not-exercised``,
``behavior: not-established``. This file pins both surfaces so a future reader
does not re-derive the wrong story, and checks that a config field with no cell
fails closed rather than silently emitting the default -- the failure shape that
cost three campaigns on 2026-08-15.
"""

import csv
import json
from pathlib import Path

import pytest

from agamemnon.engine import bram_emit


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ADMITTED_TILES = {(13, 1), (13, 2), (13, 3), (13, 4)}


def admitted_rows():
    return json.loads((CHIPDB / "bram_config_admission.json").read_text())["rows"]


def test_the_config_surface_covers_every_admitted_tile():
    """No B4 row may claim a tile whose config cells are absent."""
    claimed = set()
    for row in admitted_rows():
        scope = row["scope"]
        ys = scope["y"] if isinstance(scope["y"], list) else [scope["y"]]
        claimed.update((int(scope["x"]), int(y)) for y in ys)

    assert claimed == ADMITTED_TILES
    assert claimed <= bram_emit.ENCODABLE_BRAM_TILES

    for name, (mux, width_bits, _legal) in bram_emit.EXPERIMENTAL_FIELDS.items():
        for tile in sorted(ADMITTED_TILES):
            cells = bram_emit.CELLS.get((tile[0], tile[1], mux), {})
            missing = [bit for bit in range(width_bits) if bit not in cells]
            assert not missing, "%s has no cell for bit(s) %r at X%dY%d" % (
                name, missing, tile[0], tile[1]
            )


def test_the_placement_surface_is_one_site_and_that_is_the_real_limit():
    bels = list(csv.DictReader((CHIPDB / "bram9k_bel.csv").open(newline="")))
    cells = list(csv.DictReader((CHIPDB / "bram_cell.csv").open(newline="")))
    assert {(int(r["x"]), int(r["y"])) for r in bels} == {(13, 4)}
    assert {(int(r["x"]), int(r["y"])) for r in cells} == {(13, 4)}


def test_every_admitted_config_row_is_still_behaviourally_unexercised():
    """The honest gap: these are encodings, not behaviour."""
    rows = admitted_rows()
    assert len(rows) == 39
    for row in rows:
        assert row["claim_domain"] == "config-encoding"
        assert row["scope"]["silicon"] == "not-exercised"
        assert row["scope"]["behavior"] == "not-established"


def test_the_encodable_tile_emits_the_experimental_field():
    bits = bram_emit.emit(
        13, 4, 0, 0, 0, {}, width_b=0,
        experimental={"PORTA_OUTREG": 1}, allow_experimental=True,
    )
    assert bram_emit.CELLS[(13, 4, "CFG_SELOUT_A")][0] in bits


def test_a_config_field_with_no_cell_fails_closed():
    """put() drops a missing cell silently; the experimental path must not."""
    mux = bram_emit.EXPERIMENTAL_FIELDS["PORTA_OUTREG"][0]
    saved = bram_emit.CELLS.pop((13, 4, mux))
    try:
        with pytest.raises(ValueError) as raised:
            bram_emit.emit(
                13, 4, 0, 0, 0, {}, width_b=0,
                experimental={"PORTA_OUTREG": 1}, allow_experimental=True,
            )
        assert "no decoded cell" in str(raised.value)
    finally:
        bram_emit.CELLS[(13, 4, mux)] = saved
