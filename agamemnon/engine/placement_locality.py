"""Measure how many tiles each net spans in a placed or routed design.

Placement density -- cells per occupied tile -- is a poor predictor of whether a
design will route on this fabric, because the two kinds of connection cost very
different things.  A net whose endpoints all sit in ONE tile is carried by that
tile's local OMUX->IMUX crossbar and consumes no shared routing resource.  A net
that leaves its tile must claim RMUX and tile egress, and egress is the scarce
resource (see docs/ROUTING_ADMISSION.md).

So packing more cells into a tile does not by itself help: if those cells do not
talk to each other, their nets still leave the tile and the egress demand simply
concentrates.  The quantity that tracks routability is therefore the net SPAN
distribution -- how many distinct tiles each net touches -- not the cell count
per tile.

This module computes that distribution from an ordinary nextpnr JSON document,
so a placement change can be scored before spending a routing attempt on it.  It
reads only the open flow's own output and makes no reference or comparison to
any external implementation.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field


LOCALITY_SCHEMA = "agamemnon.placement-locality.v1"

# Nets that are structurally global or constant: they are not routed as ordinary
# fabric signals, so counting their span would swamp the statistic.
_IGNORED_NETS = frozenset({"vcc", "gnd", "$true", "$false", "$undef"})

_BEL_TILE = re.compile(r"X(\d+)Y(\d+)")


@dataclass(frozen=True)
class LocalityReport:
    """Net-span statistics for one placed or routed document."""

    placed_cells: int
    occupied_tiles: int
    nets: int
    intra_tile_nets: int
    span_histogram: dict = field(default_factory=dict)

    @property
    def cells_per_tile(self):
        if not self.occupied_tiles:
            return 0.0
        return self.placed_cells / self.occupied_tiles

    @property
    def intra_tile_fraction(self):
        if not self.nets:
            return 0.0
        return self.intra_tile_nets / self.nets

    @property
    def mean_span(self):
        """Average number of tiles a net touches.

        This is the routing-demand figure: 1.0 would mean every net is carried
        entirely by local crossbars, and each whole step above 1.0 is another
        tile boundary that every net crosses on average.
        """
        if not self.nets:
            return 0.0
        total = sum(span * count for span, count in self.span_histogram.items())
        return total / self.nets

    def as_dict(self):
        return {
            "schema": LOCALITY_SCHEMA,
            "placed_cells": self.placed_cells,
            "occupied_tiles": self.occupied_tiles,
            "cells_per_tile": round(self.cells_per_tile, 4),
            "nets": self.nets,
            "intra_tile_nets": self.intra_tile_nets,
            "intra_tile_fraction": round(self.intra_tile_fraction, 6),
            "mean_span": round(self.mean_span, 4),
            "span_histogram": {str(k): v for k, v in sorted(self.span_histogram.items())},
        }


def _top_module(document):
    """Return the module carrying the design, matching the rest of the engine.

    A nextpnr document may carry helper modules; the design is the one with
    cells.  Selecting by cell count keeps this working for both pack-only and
    fully routed documents.
    """
    modules = document.get("modules") or {}
    if not modules:
        raise ValueError("document contains no modules")
    return max(modules.values(), key=lambda m: len(m.get("cells") or {}))


def _bit_to_net(module):
    mapping = {}
    for name, netname in (module.get("netnames") or {}).items():
        for bit in netname.get("bits") or ():
            if isinstance(bit, int):
                mapping[bit] = name
    return mapping


def net_locality(document):
    """Compute :class:`LocalityReport` for a parsed nextpnr JSON document.

    Cells without a ``NEXTPNR_BEL`` attribute are unplaced and are skipped, so
    this is meaningful on a pack-only document as well: it then reports only the
    portion that has been bound.
    """
    module = _top_module(document)
    bit_to_net = _bit_to_net(module)

    net_tiles = collections.defaultdict(set)
    tiles = set()
    placed = 0

    for cell in (module.get("cells") or {}).values():
        bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL") or ""
        match = _BEL_TILE.match(bel)
        if not match:
            continue
        tile = (int(match.group(1)), int(match.group(2)))
        tiles.add(tile)
        placed += 1
        for bits in (cell.get("connections") or {}).values():
            for bit in bits:
                if not isinstance(bit, int):
                    continue
                name = bit_to_net.get(bit)
                if name is None or name.lower() in _IGNORED_NETS:
                    continue
                net_tiles[name].add(tile)

    histogram = collections.Counter(len(t) for t in net_tiles.values() if t)
    return LocalityReport(
        placed_cells=placed,
        occupied_tiles=len(tiles),
        nets=sum(histogram.values()),
        intra_tile_nets=histogram.get(1, 0),
        span_histogram=dict(histogram),
    )


def net_locality_from_path(path):
    """Compute :func:`net_locality` for a nextpnr JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        return net_locality(json.load(handle))


def format_report(report):
    """Render a short human-readable summary."""
    lines = [
        "placed cells        : %d" % report.placed_cells,
        "occupied tiles      : %d" % report.occupied_tiles,
        "cells per tile      : %.2f" % report.cells_per_tile,
        "nets                : %d" % report.nets,
        "intra-tile nets     : %d (%.1f%%)"
        % (report.intra_tile_nets, report.intra_tile_fraction * 100.0),
        "mean net span       : %.2f tiles" % report.mean_span,
        "span histogram      :",
    ]
    for span in sorted(report.span_histogram):
        count = report.span_histogram[span]
        share = count / report.nets * 100.0 if report.nets else 0.0
        lines.append("    %2d tile(s): %5d  %5.1f%%" % (span, count, share))
    return "\n".join(lines)
