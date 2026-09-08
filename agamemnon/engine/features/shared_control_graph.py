"""Expose the tile shared-control routing graph, off by default.

Companion to :mod:`agamemnon.engine.features.shared_control`, which validates a
routed slice's control shape and fails closed. This module supplies the missing
*graph*: the pips a control signal needs in order to reach a tile's shared line
in the first place.

A LogicTile carries two shared lines per control family -- clock enable and
synchronous control -- reached through a tile ``CtrlMUX``::

    <fabric wire> -> LogicTILE(x,y):CtrlMUXn -> LogicTILE(x,y):TileClkEnMUX{0,1}

The destination is a **sink**: in the retained routes nothing leaves a tile
control line. Slices consume it internally, selecting which of the two lines
they take with ``CFG_CLKMUX<z>`` -- the same per-slice mux that already carries
the ``CLK`` bel pin. There is therefore no per-slice control pin to add, and this
feature adds none.

Every wire involved already exists, because ``archgen`` loads all of
``wires.csv`` and that carries 264 ``TileClkEnMUX``, 264 ``TileSyncMUX`` and 528
``CtrlMUX`` LogicTile wires. What was missing is the edges: ``rrg_edges_full.csv``
holds no ``TileClkEnMUX`` edge at all, and its ``CtrlMUX`` rows carry an empty
``cfg`` at ``group_only`` tier, so nothing could be emitted for them.

``tile_control_edges.csv`` supplies those edges with real codewords, harvested
from retained vendor routes with a branch-aware parser and differentially
validated against the emitted images: 1,758 predicted selector bits present with
none absent, and a design that ties both controls off leaves all 132 tiles at
zero.

Emission resolves a routed edge to bits and refuses anything it cannot resolve,
because a control pip dropped in silence produces an image that config-accepts
and runs with the enable stuck at the baseline value. It does not emit a
per-slice ``sync`` selection: that mapping rests on row pairing alone and every
sync observation in the corpus uses line 0, so nothing discriminates it.

Deliberately **not** in ``features.FEATURES``. Registering it there puts it on
the claim-policy emission surface, which requires an explicit approval record --
``approval_state``, ``approved_by``, a review date and a claim scope. That is a
human sign-off, not something this module can assert for itself, so the feature
stays out of the registry until it is granted. ``archgen`` calls it directly and
it is a no-op while the flag is unset, so nothing is claimed in the meantime.

**Off unless ``AGRV2K_SHARED_CONTROL_GRAPH`` is set.** With the flag unset the
graph gains no edge, so no route can use one, so ``prepare`` sees an empty pip
list and emits nothing: the routing graph, every emitted image and the retained
byte gate are untouched. Enabling it exposes edges whose *encoding* is validated but
whose *silicon behaviour through the open flow* is not, and
:mod:`shared_control` still refuses controlled flip-flop forms, so a design
cannot use them end to end yet.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from dataclasses import dataclass, field

from agamemnon.engine import control_encode

from .protocol import EmissionPhase, FeatureDescriptor


#: Environment switch. Named ``AGRV2K_`` so it forwards into WSL automatically
#: with the rest of the uarch controls.
SHARED_CONTROL_GRAPH_OPTION = "AGRV2K_SHARED_CONTROL_GRAPH"

# Lives one level up in agamemnon/engine/ rather than beside this module: the
# repository ignores *.csv globally and re-includes only ``agamemnon/engine/*.csv``,
# not the features/ subdirectory. A table placed here would be silently dropped
# from a commit and the feature would fail to load on a fresh clone.
EDGE_TABLE = Path(__file__).resolve().parent.parent / "tile_control_edges.csv"

#: Control-line families a control signal terminates on.
CONTROL_SINKS = ("TileClkEnMUX", "TileSyncMUX")

#: Sink resource -> the family name :mod:`control_encode` uses.
FAMILY_OF_SINK = {"TileClkEnMUX": "clock_enable", "TileSyncMUX": "sync"}

#: Which shared line each ``CtrlMUX`` instance drives, and from which of the two
#: source positions. Read straight off the harvested edges: instances 0 and 1
#: drive line 1 (selectors 3 and 4), instances 2 and 3 drive line 0 (selectors 0
#: and 1), with no exception in 1,074 edges.
LINE_OF_CTRL = {0: 1, 1: 1, 2: 0, 3: 0}
SOURCE_OF_CTRL = {0: "ctrl_a", 1: "ctrl_b", 2: "ctrl_a", 3: "ctrl_b"}

_WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)$")


class SharedControlEmitError(Exception):
    """A routed control edge cannot be turned into bits."""


@dataclass
class SharedControlState:
    sets: list = field(default_factory=list)
    tile_lines: dict = field(default_factory=dict)
    slice_lines: dict = field(default_factory=dict)
    routes: int = 0
    sources: int = 0


def _parse(wire):
    match = _WIRE.match(wire)
    if not match:
        raise SharedControlEmitError("unparseable control wire %r" % (wire,))
    return (int(match.group(1)), int(match.group(2)),
            match.group(3), int(match.group(4)))


def load_control_edges(path=None):
    """Read the harvested control edges.

    Rows are in ``rrg_edges_full.csv`` column shape so they can be promoted into
    that table later without reshaping.
    """
    with open(path or EDGE_TABLE, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _wire(x, y, resource):
    return "X%sY%s_%s" % (x, y, resource)


_LOGIC_TILES = None


def logic_tiles(chipdb_root=None):
    """The 132 real LogicTile coordinates, from the shipped per-slice map.

    Needed because the tile-line selector formula in :mod:`control_encode` is a
    *LogicTile* map. BRAM tiles sit at x=13 and have their own config layout, so
    the formula must not be applied there -- and the harvested corpus does
    contain 17 BramTILE control edges at (13,2), (13,3) and (13,4), which is how
    this came up.
    """
    global _LOGIC_TILES
    if _LOGIC_TILES is not None and chipdb_root is None:
        return _LOGIC_TILES
    root = Path(chipdb_root) if chipdb_root else (
        Path(__file__).resolve().parent.parent.parent / "chipdb")
    with (root / "slice_cfg.csv").open(newline="", encoding="utf-8") as handle:
        tiles = frozenset((int(row["x"]), int(row["y"]))
                          for row in csv.DictReader(handle))
    if chipdb_root is None:
        _LOGIC_TILES = tiles
    return tiles


class SharedControlGraphFeature:
    descriptor = FeatureDescriptor(
        feature_id="shared_control_graph",
        options=(SHARED_CONTROL_GRAPH_OPTION,),
        # The edge table ships beside this module rather than in chipdb/. That
        # directory is content fingerprinted and adding a file there escalates
        # to a full rebuild-and-compare of every retained qualified artifact,
        # which is a gate this data has not been through.
        chipdb_files=(),
        writable_regions=(),
        phase=EmissionPhase.ROUTING,
        evidence=("docs/CLAUDE_SHARED_CONTROL_RESOURCES_2026-09-07.md",),
        maturity="experimental",
        evidence_tier="differentially_validated",
        architecture=(
            "Add the harvested CtrlMUX and tile control-line pips so a register "
            "control signal can reach a tile's shared line."
        ),
        bitstream=(
            "Resolve each routed control edge to its selector bits: the tile "
            "line's source position, the CtrlMUX source pair, and CFG_CLKMUX<z> "
            "for slices taking line 1. Fails closed on an edge it cannot "
            "resolve."
        ),
    )

    def add_architecture(self, context):
        if not os.environ.get(SHARED_CONTROL_GRAPH_OPTION):
            return 0
        ctx, Loc = context.ctx, context.loc
        wires = context.shared["wires"]
        delay = ctx.getDelayFromNS(0.05)

        added = 0
        skipped_missing = 0
        for row in load_control_edges():
            source = _wire(row["src_x"], row["src_y"], row["src_res"])
            destination = _wire(row["dst_x"], row["dst_y"], row["dst_res"])
            # Only connect wires this device actually has. A row naming a wire
            # outside its map is skipped rather than invented.
            if source not in wires or destination not in wires:
                skipped_missing += 1
                continue
            ctx.addPip(
                name="%s.%s" % (source, destination), type="SHARED_CONTROL",
                srcWire=source, dstWire=destination, delay=delay,
                loc=Loc(int(row["dst_x"]), int(row["dst_y"]), 0),
            )
            added += 1

        context.shared["shared_control_pips"] = added
        print("AGRV2K arch: added %d shared-control pips (%d skipped, wire absent)"
              % (added, skipped_missing))
        return added

    # ---------------------------------------------------------------- emit

    def prepare(self, pips, selector_cells, slice_lines=None, options=None):
        """Resolve routed control edges to selector bits.

        ``pips`` are the ``SRC.DST`` names ``features.routing`` handed over
        rather than resolving itself; ``selector_cells`` is the shipped
        ``pips_full.csv`` map keyed ``(x, y, mux, sel)``; ``slice_lines`` is
        ``{(x, y, z): line}`` for slices that consume a shared line, which the
        packer supplies once it admits controlled registers.

        Fails closed on every unresolved edge. An unrecognised control pip must
        not be dropped in silence: that is how a design routes a control signal,
        emits nothing for it, config-accepts, and runs with the register enable
        stuck at whatever the base image left behind.
        """
        state = SharedControlState(slice_lines=dict(slice_lines or {}))

        for pip in pips:
            source_text, destination_text = pip.split(".", 1)
            sx, sy, source_family, source_index = _parse(source_text)
            dx, dy, destination_family, destination_index = _parse(destination_text)

            if destination_family in FAMILY_OF_SINK:
                family = FAMILY_OF_SINK[destination_family]
                if source_family != "CtrlMUX":
                    raise SharedControlEmitError(
                        "%s is driven by %s, but a tile control line takes only "
                        "a CtrlMUX" % (destination_text, source_text))
                if LINE_OF_CTRL[source_index] != destination_index:
                    raise SharedControlEmitError(
                        "CtrlMUX%d drives line %d, not the line %d named by %s"
                        % (source_index, LINE_OF_CTRL[source_index],
                           destination_index, destination_text))
                if (dx, dy) not in logic_tiles():
                    # The BRAM column at x=13 carries CtrlMUX and tile control
                    # lines too, and the corpus has 17 such edges -- but the
                    # selector formula is a LogicTile map and there is no
                    # decoded BramTILE equivalent. Emitting a LogicTile-shaped
                    # bit here would land on an unrelated field of a tile whose
                    # layout nobody has read.
                    raise SharedControlEmitError(
                        "X%dY%d is not a LogicTile; the tile control-line "
                        "selector map does not cover it (edge %s)"
                        % (dx, dy, pip))
                assignment = control_encode.ControlAssignment(
                    dx, dy, family, destination_index,
                    SOURCE_OF_CTRL[source_index])
                key = (dx, dy, family, destination_index)
                if state.tile_lines.get(key) not in (None, assignment.source):
                    raise SharedControlEmitError(
                        "tile (%d,%d) %s line %d is driven twice"
                        % (dx, dy, family, destination_index))
                state.tile_lines[key] = assignment.source
                state.sets.append(assignment.bit())
                state.routes += 1

            elif destination_family == "CtrlMUX":
                # Which fabric wire reaches this CtrlMUX. Tile-invariant, so the
                # source is named by resource, not by coordinate.
                low, high = control_encode.ctrlmux_source_sels(
                    destination_index, "%s%02d" % (source_family, source_index))
                for selection in (low, high):
                    entry = None
                    for name in ("CFG_CTRLMUX%d" % destination_index,
                                 "CFG_CTRLMUX"):
                        entry = selector_cells.get((dx, dy, name, selection))
                        if entry:
                            break
                    if not entry:
                        raise SharedControlEmitError(
                            "tile (%d,%d) has no CFG_CTRLMUX bit for sel %d "
                            "(edge %s)" % (dx, dy, selection, pip))
                    state.sets.append(tuple(entry))
                state.sources += 1

            else:
                raise SharedControlEmitError(
                    "%s is not a control destination" % (destination_text,))

        for (x, y, z), line in sorted(state.slice_lines.items()):
            family = "clock_enable"
            if control_encode.slice_line_confidence(family) != "exact":
                raise SharedControlEmitError(
                    "per-slice line selection for %s is not established" % family)
            if line not in (0, 1):
                raise SharedControlEmitError(
                    "slice X%dY%d_SLICE%d asks for line %r" % (x, y, z, line))
            if line == 1:
                # Clear means line 0, which the cleared baseline already gives.
                state.sets.append(control_encode.slice_line_bit(x, y, z, family))

        print("shared control: %d tile-line selections, %d CtrlMUX sources, "
              "%d slice line bits -> %d config bits"
              % (state.routes, state.sources,
                 sum(1 for line in state.slice_lines.values() if line == 1),
                 len(state.sets)))
        return state

    def writable_bits(self, state):
        return set(state.sets)

    def clear_bitstream(self, context):
        """Nothing to clear.

        Every bit this feature writes is a selector whose cleared state is the
        meaningful default -- line 0, no source -- and the baseline clear has
        already put the tile there. There is no owned region to wipe.
        """
        return 0

    def emit_bitstream(self, context):
        state = context.state
        if state is None:
            return 0
        count = 0
        for byte, mask in state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "shared_control")
                count += 1
        return count


FEATURE = SharedControlGraphFeature()

#: Descriptive alias; ``FEATURE`` is the name the registry and archgen use.
SHARED_CONTROL_GRAPH_FEATURE = FEATURE
