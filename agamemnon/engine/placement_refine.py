"""Offline study of how much net span a post-placement refinement pass can recover.

`pack_condplace` places connectivity-first but in a single greedy pass: it fills a
tile to its cap and spills, and never revisits a decision.  Measured on retained
builds it reaches roughly 12-16% single-tile nets at realistic design size.  The
question this module exists to answer is whether the remaining gap is reachable
by *refinement* -- repeatedly moving a cell to the tile where most of its
neighbours already sit -- or whether it needs a different placement formulation
altogether.

That question is worth answering before any engine change, because it can be
answered offline: the pass runs against a saved nextpnr document and is scored
with :mod:`agamemnon.engine.placement_locality`, so it needs no build, no device
database and no hardware.

**This is an analysis pass, not a placer.**  It is deliberately not wired into
the flow.  It models tile occupancy as a simple count and does not model
slice-level legality, dedicated-carry adjacency, control-set compatibility, or
routing conduction -- all of which a real placer must satisfy.  Its output is
therefore an *upper bound* on what refinement could achieve, useful for deciding
whether to build the real thing.  A span improvement here does not imply a
routable, legal, or correct placement.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass


REFINE_SCHEMA = "agamemnon.placement-refine-study.v1"

_IGNORED_NETS = frozenset({"vcc", "gnd", "$true", "$false", "$undef"})
_BEL_TILE = re.compile(r"X(\d+)Y(\d+)")

# nextpnr PlaceStrength: anything at STRENGTH_LOCKED or above was pinned by a
# hard constraint (MCU boundary, pin-packing, replay) and must not be moved.
_STRENGTH_LOCKED = 5

# Cell types bound to hard boundary sites.
_FIXED_TYPE_PREFIX = "MCU"

# Attributes that mark a cell as deliberately pinned by the uarch.
_FIXED_ATTRS = (
    "AGRV2K_BRAM_PINPACKED",
    "AGRV2K_IO_PINPACKED",
    "AGRV2K_MCU_PINPACKED",
    "AGRV2K_ROUTE_THROUGH",
    "NEXTPNR_CLUSTER",
)


@dataclass(frozen=True)
class RefineResult:
    """Outcome of the study pass."""

    moves: int
    passes: int
    span_before: int
    span_after: int
    movable_cells: int
    total_cells: int

    @property
    def span_reduction(self):
        if not self.span_before:
            return 0.0
        return (self.span_before - self.span_after) / self.span_before

    def as_dict(self):
        return {
            "schema": REFINE_SCHEMA,
            "moves": self.moves,
            "passes": self.passes,
            "total_span_before": self.span_before,
            "total_span_after": self.span_after,
            "span_reduction": round(self.span_reduction, 6),
            "movable_cells": self.movable_cells,
            "total_cells": self.total_cells,
        }


def _top_module(document):
    modules = document.get("modules") or {}
    if not modules:
        raise ValueError("document contains no modules")
    return max(modules.values(), key=lambda m: len(m.get("cells") or {}))


def _strength(cell):
    raw = (cell.get("attributes") or {}).get("BEL_STRENGTH")
    if raw is None:
        return 0
    text = str(raw)
    try:
        return int(text, 2) if set(text) <= {"0", "1"} and len(text) > 2 else int(text)
    except ValueError:
        return 0


def _is_movable(cell):
    if str(cell.get("type") or "").startswith(_FIXED_TYPE_PREFIX):
        return False
    attributes = cell.get("attributes") or {}
    if any(name in attributes for name in _FIXED_ATTRS):
        return False
    return _strength(cell) < _STRENGTH_LOCKED


def _extract(module):
    """Return (cell_tile, cell_nets, net_cells, movable) from a placed module."""
    bit_to_net = {}
    for name, netname in (module.get("netnames") or {}).items():
        for bit in netname.get("bits") or ():
            if isinstance(bit, int):
                bit_to_net[bit] = name

    cell_tile, cell_nets, movable = {}, {}, set()
    net_cells = collections.defaultdict(set)
    for name, cell in (module.get("cells") or {}).items():
        bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL") or ""
        match = _BEL_TILE.match(bel)
        if not match:
            continue
        cell_tile[name] = (int(match.group(1)), int(match.group(2)))
        if _is_movable(cell):
            movable.add(name)
        nets = set()
        for bits in (cell.get("connections") or {}).values():
            for bit in bits:
                if not isinstance(bit, int):
                    continue
                net = bit_to_net.get(bit)
                if net is None or net.lower() in _IGNORED_NETS:
                    continue
                nets.add(net)
                net_cells[net].add(name)
        cell_nets[name] = nets
    return cell_tile, cell_nets, net_cells, movable


def _total_span(cell_tile, net_cells):
    return sum(len({cell_tile[c] for c in cells if c in cell_tile}) for cells in net_cells.values())


def refine(document, tile_capacity=16, max_passes=20):
    """Greedily move cells toward their neighbours' tiles, reducing total span.

    A move is accepted only if it strictly reduces the sum over nets of the
    number of distinct tiles that net touches, and only if the destination tile
    stays within ``tile_capacity``.  Candidate destinations are restricted to
    tiles where the cell already has a connected neighbour, which is both the
    only place a move can help and what keeps the pass cheap.

    Returns ``(mutated_document_cell_tiles, RefineResult)``.  The document itself
    is not modified; the returned mapping is the proposed placement.
    """
    module = _top_module(document)
    cell_tile, cell_nets, net_cells, movable = _extract(module)
    occupancy = collections.Counter(cell_tile.values())
    span_before = _total_span(cell_tile, net_cells)

    def delta_for(cell, destination):
        """Change in total span if ``cell`` moves to ``destination``."""
        delta = 0
        for net in cell_nets.get(cell, ()):
            members = net_cells[net]
            before = {cell_tile[c] for c in members if c in cell_tile}
            after = {destination if c == cell else cell_tile[c] for c in members if c in cell_tile}
            delta += len(after) - len(before)
        return delta

    moves = 0
    passes = 0
    for passes in range(1, max_passes + 1):
        improved = 0
        # Deterministic order: the study must reproduce exactly across runs.
        for cell in sorted(movable):
            here = cell_tile[cell]
            candidates = set()
            for net in cell_nets.get(cell, ()):
                for other in net_cells[net]:
                    if other != cell and other in cell_tile:
                        candidates.add(cell_tile[other])
            candidates.discard(here)

            best_tile, best_delta = None, 0
            for destination in sorted(candidates):
                if occupancy[destination] >= tile_capacity:
                    continue
                delta = delta_for(cell, destination)
                if delta < best_delta:
                    best_tile, best_delta = destination, delta

            if best_tile is not None:
                occupancy[here] -= 1
                occupancy[best_tile] += 1
                cell_tile[cell] = best_tile
                moves += 1
                improved += 1
        if not improved:
            break

    return cell_tile, RefineResult(
        moves=moves,
        passes=passes,
        span_before=span_before,
        span_after=_total_span(cell_tile, net_cells),
        movable_cells=len(movable),
        total_cells=len(cell_tile),
    )


def locality_after_refine(document, tile_capacity=16, max_passes=20):
    """Return ``(before, after, RefineResult)`` as :mod:`placement_locality` reports.

    Lets the study be scored with exactly the metric used on the unrefined
    placement, so the two numbers are directly comparable.
    """
    from agamemnon.engine import placement_locality

    before = placement_locality.net_locality(document)
    cell_tile, result = refine(document, tile_capacity=tile_capacity, max_passes=max_passes)

    module = _top_module(document)
    _, _, net_cells, _ = _extract(module)
    histogram = collections.Counter(
        len({cell_tile[c] for c in cells if c in cell_tile}) for cells in net_cells.values()
    )
    histogram.pop(0, None)
    after = placement_locality.LocalityReport(
        placed_cells=len(cell_tile),
        occupied_tiles=len(set(cell_tile.values())),
        nets=sum(histogram.values()),
        intra_tile_nets=histogram.get(1, 0),
        span_histogram=dict(histogram),
    )
    return before, after, result
