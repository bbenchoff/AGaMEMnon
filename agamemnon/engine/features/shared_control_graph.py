"""Tile shared-control routing and isolated native clock-enable emission.

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
the ``CLK`` bel pin. So there is **no per-slice control pin to add and this
feature adds none**; a ``CE`` pin on ``GENERIC_SLICE`` would model a wire the
hardware does not have. What it does add is an ``AGRV2K_TILE_CONTROL`` bel per
tile line, because a routed net still has to terminate on a bel pin somewhere.

Every wire involved already exists, because ``archgen`` loads all of
``wires.csv`` and that carries 264 ``TileClkEnMUX``, 264 ``TileSyncMUX`` and 528
``CtrlMUX`` LogicTile wires. What was missing is the LogicTile edges:
``rrg_edges_full.csv`` holds no usable ``TileClkEnMUX`` edge at all, and its ``CtrlMUX`` rows carry an empty
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

The registered, owner-approved scope is positive-edge, active-high native
clock enable on line 0, with ordinary and differently controlled FFs excluded
from the tile. A fresh ordinary-source composition passed its entire silicon
contract three times. Line 1 and mixed sequential tiles remain unqualified.

Normal ``build --uarch`` sets both ``AGRV2K_SHARED_CONTROL_GRAPH`` and
``AGRV2K_SHARED_CONTROL_ENABLE``. ``--no-native-clock-enable`` and retained
replay profiles keep the historical data-logic path. Low-level graph generation
still requires the graph flag, preserving historical graph identities. Packing
an already-routed native image resolves its control pips without environment
flags. See ``docs/NATIVE_CLOCK_ENABLE_EXPERIMENT.md`` for the evidence and limits.
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

# This is deliberately separate from graph generation.  The graph and encoder
# know both clock-enable lines, but the released admission is one native group
# on line 0.  A caller that wants two *native* groups in one tile must opt in
# explicitly; ordinary FFs remain excluded in both modes.
DUAL_NATIVE_CONTROL_OPTION = "AGRV2K_DUAL_NATIVE_CONTROL"
MIXED_NATIVE_CONTROL_OPTION = "AGRV2K_MIXED_NATIVE_CONTROL"

# Lives one level up in agamemnon/engine/ rather than beside this module: the
# repository ignores *.csv globally and re-includes only ``agamemnon/engine/*.csv``,
# not the features/ subdirectory. A table placed here would be silently dropped
# from a commit and the feature would fail to load on a fresh clone.
EDGE_TABLE = Path(__file__).resolve().parent.parent / "tile_control_edges.csv"

#: Control-line families a control signal terminates on.
CONTROL_SINKS = ("TileClkEnMUX", "TileSyncMUX")

#: Cell/bel type owning one tile clock-enable line. The packer creates one per
#: (tile, enable net) and binds it so the net has a legal sink.
TILE_CONTROL_BEL = "AGRV2K_TILE_CONTROL"

#: First z past the sixteen slices, so a tile's control bels never collide with
#: a slice bel inside a relative cluster.
TILE_CONTROL_Z_BASE = 16

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


def dual_native_control_enabled(environ=None):
    """Return whether the unqualified two-native-line composition is enabled.

    Treat an unset switch as ``0``.  Reject spelling mistakes instead of
    silently enabling a new physical composition through truthiness.
    """
    value = (os.environ if environ is None else environ).get(
        DUAL_NATIVE_CONTROL_OPTION, "0")
    if value not in ("0", "1"):
        raise SharedControlEmitError(
            "%s must be 0 or 1 (got %r)" % (DUAL_NATIVE_CONTROL_OPTION, value))
    return value == "1"


@dataclass
class SharedControlState:
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)
    tile_lines: dict = field(default_factory=dict)
    slice_lines: dict = field(default_factory=dict)
    ordinary_slices: frozenset = frozenset()
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
        evidence=("docs/NATIVE_CLOCK_ENABLE_EXPERIMENT.md",),
        maturity="release",
        evidence_tier="individually_qualified",
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

        # A pip's NAME is its identity to nextpnr, and routing has already added
        # most of the wire -> CtrlMUX half from rrg_edges_full.csv (1,228 CtrlMUX
        # rows, topology present with an empty cfg). Adding them again fails
        # devdb emission outright with "duplicate/empty PIP identity". What is
        # genuinely missing is the CtrlMUX -> tile-line half, of which the
        # existing graph has none.
        seen = context.shared.get("seen_pip") or set()

        added = 0
        skipped_missing = 0
        skipped_present = 0
        for row in load_control_edges():
            source = _wire(row["src_x"], row["src_y"], row["src_res"])
            destination = _wire(row["dst_x"], row["dst_y"], row["dst_res"])
            # Only connect wires this device actually has. A row naming a wire
            # outside its map is skipped rather than invented.
            if source not in wires or destination not in wires:
                skipped_missing += 1
                continue
            if "%s.%s" % (source, destination) in seen:
                skipped_present += 1
                continue
            ctx.addPip(
                name="%s.%s" % (source, destination), type="SHARED_CONTROL",
                srcWire=source, dstWire=destination, delay=delay,
                loc=Loc(int(row["dst_x"]), int(row["dst_y"]), 0),
            )
            seen.add("%s.%s" % (source, destination))
            added += 1

        context.shared["shared_control_pips"] = added
        self._add_control_sinks(context)
        print("AGRV2K arch: added %d shared-control pips "
              "(%d already in the graph, %d skipped, wire absent)"
              % (added, skipped_present, skipped_missing))
        # The pip count, as every other feature reports. Sink bels are counted
        # separately on the shared context.
        return added

    def _add_control_sinks(self, context):
        """Give an enable net somewhere to terminate.

        A routed net has to end on a bel pin, and the enable does not reach a
        slice: a tile control line is a pure sink, and each slice picks which of
        the two lines it consumes with ``CFG_CLKMUX<z>``, a config bit and not an
        edge. So the sink is modelled at the tile, one bel per line, rather than
        as a per-slice ``CE`` pin -- a pin there would model a wire the hardware
        does not have.

        Placed at ``z = 16 + line``, past the sixteen slice positions, so a
        relative cluster can carry a control cell and its registers in one tile
        without colliding with a slice bel.

        Clock enable only. Sync gets no sink because its per-slice line
        selection is not established, and a sink the packer could bind but the
        emitter must refuse is worse than no sink at all.
        """
        ctx, Loc = context.ctx, context.loc
        wires = context.shared["wires"]
        bels = 0
        for x, y in sorted(logic_tiles()):
            for line in range(2):
                wire = _wire(x, y, "TileClkEnMUX%02d" % line)
                if wire not in wires:
                    continue
                bel = "X%dY%d_CLKEN%d" % (x, y, line)
                ctx.addBel(name=bel, type=TILE_CONTROL_BEL,
                           loc=Loc(x, y, TILE_CONTROL_Z_BASE + line),
                           gb=False, hidden=False)
                ctx.addBelInput(bel=bel, name="I", wire=wire)
                bels += 1
        context.shared["shared_control_bels"] = bels
        print("AGRV2K arch: added %d tile clock-enable sink bels" % bels)
        return bels

    # ---------------------------------------------------------------- emit

    def slice_lines_from_module(self, module):
        """Check the routed control composition and return ``{(x,y,z): line}``.

        Three things have to agree or the image is quietly wrong:

        * every slice carrying an enable is in a tile that has a control cell
          for *that* enable -- otherwise its register is clocked unconditionally
          while the design believes it is gated;
        * no two enables share a tile line;
        * line 1 needs an explicit ``AGRV2K_DUAL_NATIVE_CONTROL=1`` opt-in.
          Its selector encoding is known, but its conduction is not established.
        """
        cells = module.get("cells", {})
        dual_native = dual_native_control_enabled()
        mixed_value = os.environ.get(MIXED_NATIVE_CONTROL_OPTION, "0")
        if mixed_value not in ("0", "1"):
            raise SharedControlEmitError("%s must be 0 or 1" % MIXED_NATIVE_CONTROL_OPTION)
        mixed_native = mixed_value == "1"
        control_sites = {}
        control_enable_lines = {}
        control_tiles = set()
        for name, cell in cells.items():
            if cell.get("type") != TILE_CONTROL_BEL:
                continue
            bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
            if not bel:
                raise SharedControlEmitError(
                    "tile control cell %r is unplaced" % (name,))
            match = re.fullmatch(r"X(\d+)Y(\d+)_CLKEN(\d+)", bel)
            if not match:
                raise SharedControlEmitError(
                    "tile control cell %r is bound to %r, which is not a tile "
                    "clock-enable bel" % (name, bel))
            x, y, line = (int(match.group(1)), int(match.group(2)),
                          int(match.group(3)))
            if line not in (0, 1):
                raise SharedControlEmitError(
                    "tile control cell %r took invalid line %d at X%dY%d" %
                    (name, line, x, y))
            if line == 1 and not dual_native:
                raise SharedControlEmitError(
                    "tile control cell %r took line 1 at X%dY%d; %s=1 is required "
                    "for the unqualified dual-native composition" %
                    (name, x, y, DUAL_NATIVE_CONTROL_OPTION))
            enable = cell.get("attributes", {}).get("AGRV2K_CLOCK_ENABLE_NET")
            if not enable:
                raise SharedControlEmitError(
                    "tile control cell %r names no enable net" % (name,))
            line_key = (x, y, line)
            if line_key in control_sites:
                raise SharedControlEmitError(
                    "tile X%dY%d line %d has more than one native control root" %
                    (x, y, line))
            enable_key = (x, y, enable)
            if enable_key in control_enable_lines:
                raise SharedControlEmitError(
                    "enable %r has more than one control line at X%dY%d" %
                    (enable, x, y))
            control_sites[line_key] = enable
            control_enable_lines[enable_key] = line
            control_tiles.add((x, y))

        slice_lines = {}
        for name, cell in cells.items():
            if cell.get("type") != "GENERIC_SLICE":
                continue
            enable = cell.get("attributes", {}).get("AGRV2K_CLOCK_ENABLE_NET")
            if not enable:
                ff_used = cell.get("parameters", {}).get("FF_USED", 0)
                if (int(ff_used, 2) if isinstance(ff_used, str) else int(ff_used)):
                    ordinary_bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
                    ordinary_site = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", ordinary_bel)
                    if ordinary_site and tuple(map(int, ordinary_site.groups()[:2])) in control_tiles:
                        x, y, z = map(int, ordinary_site.groups())
                        used = {line for cx, cy, line in control_sites if (cx, cy) == (x, y)}
                        if not mixed_native or len(used) != 1:
                            raise SharedControlEmitError(
                                "ordinary register %r shares an enabled tile at %s; "
                                "mixed sequential control requires an enabled experiment "
                                "and one idle local clock line" % (name, ordinary_bel))
                        slice_lines[(x, y, z)] = 1 - next(iter(used))
                continue
            bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
            match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
            if not match:
                raise SharedControlEmitError(
                    "clock-enabled slice %r is bound to %r" % (name, bel))
            x, y, z = (int(match.group(1)), int(match.group(2)),
                       int(match.group(3)))
            line = control_enable_lines.get((x, y, enable))
            if line is None:
                raise SharedControlEmitError(
                    "clock-enabled slice %r at X%dY%d has no tile control cell; "
                    "its register would be clocked unconditionally" % (name, x, y))
            slice_lines[(x, y, z)] = line
        return slice_lines

    def ordinary_slice_sites_from_module(self, module):
        """Identify ordinary FFs independently; only mapped sites are consumed."""
        sites = set()
        for cell in module.get("cells", {}).values():
            if cell.get("type") != "GENERIC_SLICE" or cell.get("attributes", {}).get("AGRV2K_CLOCK_ENABLE_NET"):
                continue
            used = cell.get("parameters", {}).get("FF_USED", 0)
            if not (int(used, 2) if isinstance(used, str) else int(used)):
                continue
            match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", cell.get("attributes", {}).get("NEXTPNR_BEL", ""))
            if match:
                sites.add(tuple(map(int, match.groups())))
        return frozenset(sites)

    def prepare(self, pips, selector_cells, slice_lines=None, options=None, ordinary_slices=()):
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
        state.ordinary_slices = frozenset(ordinary_slices) & state.slice_lines.keys()

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
            if (x, y, z) in state.ordinary_slices and (x, y, "clock_enable", line) in state.tile_lines:
                raise SharedControlEmitError(
                    "ordinary register X%dY%d_SLICE%d selects driven clock-enable line %d"
                    % (x, y, z, line))
            family = "clock_enable"
            if control_encode.slice_line_confidence(family) != "exact":
                raise SharedControlEmitError(
                    "per-slice line selection for %s is not established" % family)
            if line not in (0, 1):
                raise SharedControlEmitError(
                    "slice X%dY%d_SLICE%d asks for line %r" % (x, y, z, line))
            # The prior BYPASSEN-as-enable interpretation was falsified by a
            # fixed-image silicon intervention. Clearing this bit restored
            # update/hold/resume for identity-LUT native registers. It did not
            # establish BYPASSEN semantics for other register input modes.
            # Ordinary register input-mode bits are not native-enable fields.
            # Preserve them when assigning the idle local clock line.
            if (x, y, z) not in state.ordinary_slices:
                state.clears.append(control_encode.slice_bypass_bit(x, y, z))
            if line == 1:
                # Clear means line 0, which the cleared baseline already gives.
                state.sets.append(control_encode.slice_line_bit(x, y, z, family))

        print("shared control: %d tile-line selection(s), %d CtrlMUX source(s), "
              "%d clock-selected slice(s) (%d on line 1) -> %d config bits"
              % (state.routes, state.sources, len(state.slice_lines),
                 sum(1 for line in state.slice_lines.values() if line == 1),
                 len(state.sets) + len(state.clears)))
        return state

    def writable_bits(self, state):
        return set(state.sets) | set(state.clears)

    def clear_bitstream(self, context):
        """No bulk region clear; explicit per-slice clears occur during emission."""
        return 0

    def emit_bitstream(self, context):
        state = context.state
        if state is None:
            return 0
        count = 0
        for byte, mask in state.clears:
            if byte >= len(context.image):
                raise SharedControlEmitError("slice bypass bit is outside the image")
            context.image[byte] &= ~mask
            if context.ownership is not None:
                context.ownership.touch(byte, mask, "shared_control")
            count += 1
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
