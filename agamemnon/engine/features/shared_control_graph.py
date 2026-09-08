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

Deliberately **not** in ``features.FEATURES``. Registering it there puts it on
the claim-policy emission surface, which requires an explicit approval record --
``approval_state``, ``approved_by``, a review date and a claim scope. That is a
human sign-off, not something this module can assert for itself, so the feature
stays out of the registry until it is granted. ``archgen`` calls it directly and
it is a no-op while the flag is unset, so nothing is claimed in the meantime.

**Off unless ``AGRV2K_SHARED_CONTROL_GRAPH`` is set.** With the flag unset this
adds nothing, so the routing graph, every emitted image and the retained byte
gate are untouched. Enabling it exposes edges whose *encoding* is validated but
whose *silicon behaviour through the open flow* is not, and
:mod:`shared_control` still refuses controlled flip-flop forms, so a design
cannot use them end to end yet.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

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


def load_control_edges(path=None):
    """Read the harvested control edges.

    Rows are in ``rrg_edges_full.csv`` column shape so they can be promoted into
    that table later without reshaping.
    """
    with open(path or EDGE_TABLE, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _wire(x, y, resource):
    return "X%sY%s_%s" % (x, y, resource)


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
            "None yet: the selector codewords are decoded and validated but no "
            "emission path consumes them."
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

    def clear_bitstream(self, context):
        """Nothing to clear: this feature owns no writable region.

        ``writable_regions`` is empty by design. The selector codewords are
        decoded and validated, but no emission path consumes them yet, so the
        feature must not touch a single image byte.
        """
        return 0

    def emit_bitstream(self, context):
        """Emit nothing, for the same reason :meth:`clear_bitstream` clears nothing."""
        return 0


FEATURE = SharedControlGraphFeature()

#: Descriptive alias; ``FEATURE`` is the name the registry and archgen use.
SHARED_CONTROL_GRAPH_FEATURE = FEATURE
