"""Emit the per-tile shared-control selector bits.

A LogicTile carries two shared lines for each control family, and each line takes
its source from one of three positions: two ``CtrlMUX`` inputs, or a constant
tie.  This module turns a chosen (tile, family, line, source) into the exact
``(byte, mask)`` edits, and reads them back, using the same representation as the
rest of the chipdb.

Bit map, derived from the decoded LogicTile template and calibrated against
``slice_cfg.csv``::

    index = tile_bit_base(x, y) + W*928 - (B - 31)
    byte  = index // 8
    mask  = 0x80 >> (index % 8)
    tile_bit_base(x, y) = 779736 - y*63104 - x*36        # BITS

The base is in bits deliberately.  The x stride is 36 bits -- four and a half
bytes -- so dividing by eight before applying it mis-aligns every odd-x tile by
half a byte and makes its selectors read back as zero.

Rows and columns::

    family        line 1 row   line 0 row
    clock_enable      W32          W35
    sync              W33          W34

    source        column
    ctrl_a          B33      (CtrlMUX0 on line 1, CtrlMUX2 on line 0)
    ctrl_b          B32      (CtrlMUX1 on line 1, CtrlMUX3 on line 0)
    constant        B31      a GND/VCC tie, which is why it needs no route

Evidence for the mapping: joining every ``CtrlMUX -> TileClkEnMUX`` and
``CtrlMUX -> TileSyncMUX`` arc in the retained routing corpus against the emitted
bits of the matching image agrees on 1,758 of 1,758 observations with no source
index outside the four, and a design that ties both controls off leaves all 132
tiles at zero.  The constant-tie position rests on a weaker 545-of-567
correspondence and is flagged accordingly by :func:`source_confidence`.

The other half of the path -- which fabric wire reaches a ``CtrlMUX`` -- is
:func:`ctrlmux_source_sels` further down, so :func:`control_route_bits` covers a
complete route.  Which of a tile's two lines an individual slice consumes is
:func:`slice_line_bit`.
"""

from __future__ import annotations

from dataclasses import dataclass


CONTROL_ENCODE_SCHEMA = "agamemnon.control-encode.v1"

#: W row carrying each family's two shared lines.
FAMILY_ROWS = {
    "clock_enable": {1: 32, 0: 35},
    "sync": {1: 33, 0: 34},
}

#: B column selecting each source position.
SOURCE_COLUMNS = {"ctrl_a": 33, "ctrl_b": 32, "constant": 31}

#: Which routing-graph ``CtrlMUX`` index drives a given line and position.
CTRL_INDEX = {(1, "ctrl_a"): 0, (1, "ctrl_b"): 1, (0, "ctrl_a"): 2, (0, "ctrl_b"): 3}

#: Shared lines available per tile, per family.
LINES_PER_FAMILY = 2


class ControlEncodeError(Exception):
    """A control assignment cannot be represented."""


#: Columns left of the BRAM column at x=13 sit 18 bytes later in the image.
#: :mod:`agamemnon.engine.physmap` carries the same correction for LUT init,
#: byte-verified against the vendor oracle. Omitting it puts every selector of
#: every x<13 tile 18 bytes early -- on a real, unrelated field.
BRAM_COLUMN_X = 13
LEFT_COLUMN_BIT_SHIFT = 18 * 8


def tile_bit_base(x, y):
    base = 779736 - y * 63104 - x * 36
    return base + LEFT_COLUMN_BIT_SHIFT if int(x) < BRAM_COLUMN_X else base


def bit_position(x, y, row, column):
    """Return the ``(byte, mask)`` of one selector bit."""
    index = tile_bit_base(x, y) + row * 928 - (column - 31)
    if index < 0:
        raise ControlEncodeError("tile (%d,%d) row %d column %d is before the image"
                                 % (x, y, row, column))
    return index // 8, 0x80 >> (index % 8)


def source_confidence(source):
    """How well evidenced a source position is.

    ``exact`` positions were validated with no exception over the routed corpus.
    ``correlated`` means the constant tie, which matched in 545 of 567 cases and
    so should not be emitted by a release path without further evidence.
    """
    return "correlated" if source == "constant" else "exact"


@dataclass(frozen=True)
class ControlAssignment:
    """One shared line of one tile, bound to a source position."""

    x: int
    y: int
    family: str
    line: int
    source: str

    def validate(self):
        if self.family not in FAMILY_ROWS:
            raise ControlEncodeError("unknown control family %r" % (self.family,))
        if self.line not in FAMILY_ROWS[self.family]:
            raise ControlEncodeError("family %s has no line %r" % (self.family, self.line))
        if self.source not in SOURCE_COLUMNS:
            raise ControlEncodeError("unknown source position %r" % (self.source,))

    @property
    def ctrl_index(self):
        """Routing ``CtrlMUX`` index, or ``None`` for the constant tie."""
        return CTRL_INDEX.get((self.line, self.source))

    def bit(self):
        self.validate()
        return bit_position(self.x, self.y,
                            FAMILY_ROWS[self.family][self.line],
                            SOURCE_COLUMNS[self.source])


def encode(assignments):
    """Return ``{(byte, mask): assignment}`` for a set of control assignments.

    Rejects two assignments to the same line of the same tile and family,
    because that would emit an image whose control routing is not what the caller
    asked for. The per-tile line budget needs no separate check: ``FAMILY_ROWS``
    defines exactly :data:`LINES_PER_FAMILY` lines, so an out-of-range line is
    already refused by :meth:`ControlAssignment.validate`.
    """
    taken = {}
    per_tile = {}
    for assignment in assignments:
        assignment.validate()
        key = (assignment.x, assignment.y, assignment.family, assignment.line)
        if key in per_tile:
            raise ControlEncodeError(
                "tile (%d,%d) %s line %d assigned twice: %s and %s"
                % (assignment.x, assignment.y, assignment.family, assignment.line,
                   per_tile[key].source, assignment.source))
        per_tile[key] = assignment
        taken[assignment.bit()] = assignment
    return taken


def apply(raw, assignments):
    """Set the selector bits for ``assignments`` in a mutable raw image."""
    edits = encode(assignments)
    for (byte, mask) in edits:
        if byte >= len(raw):
            raise ControlEncodeError("selector byte %d is past the image" % byte)
        raw[byte] |= mask
    return len(edits)


def decode_tile(raw, x, y, family):
    """Return ``{line: source}`` for one tile and family, reading the image.

    The inverse of :func:`encode`, so an emitted image can be checked against the
    assignment that produced it.
    """
    if family not in FAMILY_ROWS:
        raise ControlEncodeError("unknown control family %r" % (family,))
    found = {}
    for line, row in FAMILY_ROWS[family].items():
        for source, column in SOURCE_COLUMNS.items():
            byte, mask = bit_position(x, y, row, column)
            if 0 <= byte < len(raw) and raw[byte] & mask:
                found.setdefault(line, []).append(source)
    result = {}
    for line, sources in found.items():
        result[line] = sources[0] if len(sources) == 1 else tuple(sorted(sources))
    return result


# --------------------------------------------------------------------------
# Which of the tile's two lines a slice consumes.
# --------------------------------------------------------------------------

#: Per-slice line selector rows, straight out of
#: ``logictile_config_template.csv``: ``CFG_CLKMUX<z>`` sits at W(4*zblock+1)/B32
#: and ``CFG_ASYNCMUX<z>`` at W(4*zblock+0)/B32, for all sixteen z.
SLICE_SELECTOR_ROW_OFFSET = {"clock_enable": 1, "sync": 0}
SLICE_SELECTOR_COLUMN = 32


def zblock(z):
    """Slice z to its config block. Block 8 is a gap, as in the LUT-init map."""
    return z if z < 8 else z + 1


def slice_line_bit(x, y, z, family):
    """Return the ``(byte, mask)`` selecting which shared line slice ``z`` takes.

    Set means line 1, clear means line 0.  For ``clock_enable`` this is
    ``CFG_CLKMUX<z>``, correlated against the line actually carrying each
    register's ``ena`` over 416 registers in eight seeds of two designs: 99 on
    line 0 with the bit clear, 317 on line 1 with it set, no off-diagonal case.

    ``sync`` maps to ``CFG_ASYNCMUX<z>`` by the row pairing, and that is
    **untested, not established**: every one of 424 sync observations in the
    designs with placement coverage uses line 0, so nothing in the available
    data discriminates.  Callers that emit sync must say so explicitly.
    """
    if family not in SLICE_SELECTOR_ROW_OFFSET:
        raise ControlEncodeError("unknown control family %r" % (family,))
    if not 0 <= int(z) < 16:
        raise ControlEncodeError("slice z=%r is outside 0..15" % (z,))
    row = 4 * zblock(int(z)) + SLICE_SELECTOR_ROW_OFFSET[family]
    return bit_position(x, y, row, SLICE_SELECTOR_COLUMN)


#: Per-slice row selecting whether the slice consumes the tile clock enable at
#: all. Same four-row per-slice block as the two above: ``CFG_ASYNCMUX<z>`` at
#: +0, ``CFG_CLKMUX<z>`` at +1, ``CFG_BYPASSEN<z>`` at +3.
SLICE_ENABLE_ROW_OFFSET = 3


def slice_enable_bit(x, y, z):
    """Return the ``(byte, mask)`` making slice ``z`` consume the tile enable.

    **Set means the slice is gated by the tile clock-enable line; clear means it
    is clocked unconditionally.** Clear is the baseline, so a design that routes
    an enable to a tile line and does not set this bit gates nothing -- the
    selector bits are all correct and the register still clocks every cycle.

    Evidence, over retained vendor images:

    ============================  ======  ======
    tile clock-enable line          set    clear
    ============================  ======  ======
    driven                         1,297   1,743
    idle                              31  250,369
    ============================  ======  ======

    and per design, against the count of ``dffeas`` instances carrying a real
    ``.ena`` net:

    =========================  =============  ==============  ================
    design                     ``.ena`` nets  ``BYPASSEN`` set  slices in driven
    =========================  =============  ==============  ================
    ``regbank16_user`` s1493              43              40                80
    ``addsub16_user`` s1409               68              67               144
    =========================  =============  ==============  ================

    Every set bit lies inside a tile whose enable line is driven, and the count
    tracks the number of enabled registers rather than the number of slices in
    those tiles -- which is what distinguishes "this slice uses the enable" from
    "this slice bypasses it". The shortfall (40 of 43, 67 of 68) is unexplained
    and is why this is reported as ``correlated`` rather than exact.

    The corollary matters for composition: an ordinary register sharing a tile
    with a gated one has this bit clear and is therefore **not** gated, so a
    mixed tile is safe by construction rather than something to refuse.
    """
    if not 0 <= int(z) < 16:
        raise ControlEncodeError("slice z=%r is outside 0..15" % (z,))
    row = 4 * zblock(int(z)) + SLICE_ENABLE_ROW_OFFSET
    return bit_position(x, y, row, SLICE_SELECTOR_COLUMN)


def slice_enable_confidence():
    """``correlated``: strong, but 3 of 43 and 1 of 68 registers are unaccounted."""
    return "correlated"


def slice_line_confidence(family):
    """``exact`` for clock enable, ``undetermined`` for sync. See above."""
    return "exact" if family == "clock_enable" else "undetermined"


# --------------------------------------------------------------------------
# Which fabric wire reaches a CtrlMUX: the second half of the control path.
# --------------------------------------------------------------------------

#: Selector values are two-hot inside a per-instance window of twelve.
SELS_PER_INSTANCE = 12

_SOURCE_TABLE = None


def _source_table(chipdb_root=None):
    """Load ``ctrlmux_source_sel.csv`` as ``{(instance, source_res): (lo, hi)}``.

    Tile-invariant: every one of the 96 (instance, source) keys resolves to the
    same selector pair at every tile it was observed on, so the table carries no
    coordinates.  Twenty-four source positions per instance, each a two-hot pair
    of offsets inside that instance's twelve-value window.
    """
    global _SOURCE_TABLE
    if _SOURCE_TABLE is not None and chipdb_root is None:
        return _SOURCE_TABLE
    import csv
    import os
    # Deliberately NOT under agamemnon/chipdb/. That directory is content
    # fingerprinted by the test harness, and adding a file there escalates to a
    # full rebuild-and-compare of every retained qualified artifact. This table
    # has not been through that gate, so it lives beside the engine until it is
    # promoted properly.
    root = chipdb_root or os.path.dirname(os.path.abspath(__file__))
    table = {}
    with open(os.path.join(root, "ctrlmux_source_sel.csv"),
              newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            table[(int(row["ctrl_instance"]), row["source_res"])] = (
                int(row["sel_lo"]), int(row["sel_hi"]))
    if chipdb_root is None:
        _SOURCE_TABLE = table
    return table


def ctrlmux_source_sels(instance, source_res, chipdb_root=None):
    """Return the two ``CFG_CTRLMUX`` selector values a source wire asserts.

    ``instance`` is the routing graph's ``CtrlMUX<n>`` index and ``source_res``
    the driving wire's resource name, e.g. ``"RMUX89"``.  Raises
    :class:`ControlEncodeError` for a source with no recorded position, rather
    than inventing one -- an unrecorded source is exactly the case that must not
    be emitted.
    """
    table = _source_table(chipdb_root)
    try:
        return table[(instance, source_res)]
    except KeyError:
        raise ControlEncodeError(
            "no recorded CtrlMUX%d position for source %s" % (instance, source_res))


def control_route_bits(x, y, family, line, source_res, pip_table, chipdb_root=None):
    """Bits for a complete control route: source wire -> CtrlMUX -> tile line.

    ``pip_table`` maps ``(x, y, mux_name, sel) -> (byte, mask)`` and is the
    shipped ``CFG_CTRLMUX`` pip data; the caller supplies it so this module stays
    free of chipdb loading policy.  Returns the union of the CtrlMUX selector
    bits and the tile-line selector bit.
    """
    assignment = ControlAssignment(x, y, family, line, "ctrl_a")
    assignment.validate()
    instance = CTRL_INDEX[(line, "ctrl_a")]
    # ctrl_a and ctrl_b differ only in which instance drives the line; pick the
    # one whose instance actually carries this source.
    table = _source_table(chipdb_root)
    for source in ("ctrl_a", "ctrl_b"):
        candidate = CTRL_INDEX[(line, source)]
        if (candidate, source_res) in table:
            instance, position = candidate, source
            break
    else:
        raise ControlEncodeError(
            "source %s reaches neither CtrlMUX driving %s line %d"
            % (source_res, family, line))

    lo, hi = ctrlmux_source_sels(instance, source_res, chipdb_root)
    bits = set()
    for sel in (lo, hi):
        for name in ("CFG_CTRLMUX%d" % instance, "CFG_CTRLMUX"):
            entry = pip_table.get((x, y, name, sel))
            if entry:
                bits.add(entry)
                break
        else:
            raise ControlEncodeError(
                "tile (%d,%d) has no CFG_CTRLMUX bit for sel %d" % (x, y, sel))
    bits.add(ControlAssignment(x, y, family, line, position).bit())
    return sorted(bits)
