"""Shared fail-closed loading and normalization of routing selector evidence."""
from __future__ import annotations

import os

from . import chipdb_schema


FILENAME = "sel_edge_pairs.agdb"


def load_clean_edges(data_dir):
    path = os.path.join(data_dir, FILENAME)
    datasets, _ = chipdb_schema.load(path, expected=("clean_edge",))
    return datasets["clean_edge"]


def relative_edges(clean_edges):
    """Return unanimous tile-relative selectors and rejected relative keys.

    A relative key is promoted only if every known physical occurrence agrees.
    One conflicting pair removes the key completely.
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
    for key in conflicts:
        relative.pop(key, None)
    return relative, frozenset(conflicts)
