"""Shared fail-closed loading and normalization of routing selector evidence."""
from __future__ import annotations

import os

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
NONPORTABLE_RELATIVE_KEYS = frozenset({("RMUX", 69, "RMUX", 15, 0, 0)})


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
