"""Shared fail-closed loading and normalization of routing selector evidence."""
from __future__ import annotations

import os
import re

from . import chipdb_schema


FILENAME = "sel_edge_pairs.agdb"

# Agreement among observations is not proof of translation invariance. This
# same-tile edge is observed only in column 20 (ten rows, pair 0/8). Applying
# it at X14Y7 fails to deliver reset: a regbank16 image fails 3/3; replacing
# only CFG_RMUX11 block 3 with the physically observed X15Y7_RMUX63 input
# (pair 5/7) passes 3/3. Exactly four payload bits differ, all downstream routes
# and logic unchanged. Do not export that boundary observation to other tiles.
# Physical observations remain usable at their exact coordinates. This rejects
# a nonportable inference, not the existence of every possible encoding of the
# edge. Failing image: 346ec0e81dd599fe1bebe97be2d7dce29925cd0880372e38b25e93709ec85307.
# Passing image: f0e6d77b32bd196ba6cda3802a05658ca8af04118b6b8e219439c26c8e66f49e.
# The north-boundary RMUX07 -> RMUX46 observation is also not portable:
# all supporting destinations are row 3, pair 2/9. At X14Y12 that pair has
# exact evidence for X14Y8_RMUX55, not X14Y11_RMUX07. A waitstate16 address
# feedback route using the translation fails; rerouting its return passes
# all 312 original observations in three silicon runs, with logic/placement
# unchanged (one scratch route also changes). Preserve the exact row-3
# observations, but do not infer the same selector elsewhere.
# Failing image: 73c9826375b7c3261e52e766f9793e457350402d143406dc8de1e66d78b3bf2c.
# Passing image: c6c47be7dcc6865f207a6afa0817d7d58f0d76ba72375615c6e0c32730d95bf4.
NONPORTABLE_RELATIVE_KEYS = frozenset({
    ("RMUX", 69, "RMUX", 15, 0, 0),
    ("RMUX", 46, "RMUX", 7, 0, 1),
    # RMUX87 -> RMUX59 has the same boundary-only inference problem:
    # supporting exact destinations are row 3; at X14Y12 pair 2/9 has
    # exact evidence for X14Y8_RMUX39. The original ALU target branch
    # fails DC capture while siblings work; a two-selector route-only
    # bypass repairs all 512 observations in three silicon runs.
    # Withdraw the unsupported translation, retaining exact observations.
    ("RMUX", 59, "RMUX", 87, 0, 1),
})

_WIRE = re.compile(r"X(-?\d+)Y(-?\d+)_([A-Za-z]+)(\d+)")


def nonportable_translation(clean_edges, source, destination):
    """Reject a withdrawn translation even when a supplemental path repeats it.

    A path listing is not an independent selector observation. Exact physical
    selector evidence remains authoritative at its own coordinates.
    """
    src, dst = _WIRE.fullmatch(source), _WIRE.fullmatch(destination)
    if src is None or dst is None:
        return False
    sx, sy, sf, si = src.groups()
    dx, dy, df, di = dst.groups()
    sx, sy, si, dx, dy, di = map(int, (sx, sy, si, dx, dy, di))
    relative = (df, di, sf, si, dx - sx, dy - sy)
    exact = (dx, dy, df, di, sf, sx, sy, si)
    return relative in NONPORTABLE_RELATIVE_KEYS and exact not in clean_edges


def load_clean_edges(data_dir):
    path = os.path.join(data_dir, FILENAME)
    datasets, _ = chipdb_schema.load(path, expected=("clean_edge",))
    return datasets["clean_edge"]


def relative_edges(clean_edges):
    """Return unanimous tile-relative selectors and rejected relative keys.

    A relative key is promoted only if every known physical occurrence agrees.
    Conflicting pairs and experimentally nonportable translations are rejected.
    This does not remove the original coordinate-specific observations.
    """
    relative = {}
    conflicts = set()
    for (dx, dy, df, di, sf, sx, sy, si), pair in clean_edges.items():
        key = (df, di, sf, si, dx - sx, dy - sy)
        pair = tuple(pair)
        if key in relative and relative[key] != pair:
            conflicts.add(key)
        else:
            relative[key] = pair
    conflicts.update(NONPORTABLE_RELATIVE_KEYS.intersection(relative))
    for key in conflicts:
        relative.pop(key, None)
    return relative, frozenset(conflicts)
