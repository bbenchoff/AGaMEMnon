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

Out of scope: this emits which *position* a line selects, not the twelve
``CFG_CTRLMUX`` bits per ``CtrlMUX`` instance that choose which fabric wire
reaches it.  Those are laid out (four instances of twelve, indices 0-23 on the
line-1 rows and 24-47 on line-0) but their encoding is not decoded, so a complete
control route still needs that half.
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


def tile_bit_base(x, y):
    return 779736 - y * 63104 - x * 36


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
