#!/usr/bin/env python3
"""One-time trusted migration from historical pickle caches to AGDB schema 1."""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

from agamemnon.engine import chipdb_schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chipdb", type=Path)
    args = parser.parse_args()
    root = args.chipdb
    with (root / "sel_edge_pairs.pkl").open("rb") as stream:
        exact = pickle.load(stream)
    if exact.get("version") != 1:
        raise ValueError("unsupported sel_edge_pairs pickle")
    chipdb_schema.dump(
        root / "sel_edge_pairs.agdb", {"clean_edge": exact["table"]},
        metadata={
            "source_format": "sel_edge_pairs.pkl/version-1",
            "stats_repr": repr(exact.get("stats", {})),
        },
    )
    with (root / "train_lut.pkl").open("rb") as stream:
        train = pickle.load(stream)
    chipdb_schema.dump(
        root / "train_lut.agdb", {"train_lut": train},
        metadata={"source_format": "train_lut.pkl"},
    )
    with (root / "_sel_tables2.pkl").open("rb") as stream:
        geom, absolute, group_context = pickle.load(stream)
    chipdb_schema.dump(
        root / "sel_tables.agdb",
        {"geom_rmux": geom, "absolute": absolute, "group_context": group_context},
        metadata={"source_format": "_sel_tables2.pkl"},
    )
    for path in (root / "sel_edge_pairs.agdb", root / "train_lut.agdb", root / "sel_tables.agdb"):
        print(path, path.stat().st_size)


if __name__ == "__main__":
    main()
