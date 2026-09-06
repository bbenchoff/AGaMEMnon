"""Coordinate-specific BRAM routing facts and complete selector fields."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re

TABLE = "bram_multisite_routes.csv"
CORRIDOR_TABLE = "bram_multisite_corridors.csv"
FIELDS = ("src_wire", "dst_wire", "pip_type", "cfg_group",
          "clear_selectors", "set_selectors", "evidence")
WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)")

def endpoint(wire):
    match = WIRE.fullmatch(wire)
    if match is None:
        raise ValueError("malformed BRAM routing endpoint: %s" % wire)
    return int(match[1]), int(match[2]), match[3], int(match[4])

@dataclass(frozen=True)
class BramRoute:
    source: str
    destination: str
    pip_type: str
    config: str
    clear: tuple[int, ...]
    set_bits: tuple[int, ...]

def _load_routes(chipdb_root, table):
    routes = []
    seen = set()
    codeword_sources = {}
    with (Path(chipdb_root) / table).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("BRAM routing table has incorrect columns")
        for row in reader:
            source, destination = row["src_wire"], row["dst_wire"]
            sx, sy, sf, si = endpoint(source)
            dx, dy, df, di = endpoint(destination)
            if table == CORRIDOR_TABLE and (sf != "RMUX" or df not in ("RMUX", "IMUX")):
                raise ValueError("unsupported BRAM logic-side corridor family")
            if table == TABLE and not ((sx == 13 and sy in (3, 4)) or (dx == 13 and dy in (3, 4))):
                raise ValueError("BRAM route has no witnessed site endpoint")
            key = (source, destination)
            if key in seen:
                raise ValueError("duplicate BRAM route: %r" % (key,))
            seen.add(key)
            clear = tuple(int(s) for s in row["clear_selectors"].split(";") if s)
            sets = tuple(int(s) for s in row["set_selectors"].split(";") if s)
            widths = {"RMUX": (6, 10), "IMUX": (4, 12),
                      "TMUX": (16, 8), "KMUX": (16, 9),
                      "SeamMUX": (6, 6), "TileClkMUX": (2, 4)}
            if df not in widths or not row["evidence"]:
                raise ValueError("unsupported or unbound BRAM selector field")
            per_group, width = widths[df]
            expected_config = "CFG_" + df + (str(di // per_group) if df in ("RMUX", "IMUX") else "")
            expected_clear = tuple(range((di % per_group) * width, (di % per_group + 1) * width))
            if row["cfg_group"] != expected_config or clear != expected_clear:
                raise ValueError("BRAM route does not describe a complete destination field")
            if len(set(sets)) != len(sets) or not set(sets).issubset(clear):
                raise ValueError("BRAM route sets bits outside its selector field")
            clock = df in ("SeamMUX", "TileClkMUX")
            if row["pip_type"] != ("GCLK0_BRAM_BRANCH" if clock else "ROUTE"):
                raise ValueError("BRAM route has incorrect clock classification")
            codeword = (destination, row["cfg_group"], frozenset(sets))
            if codeword in codeword_sources and codeword_sources[codeword] != source:
                raise ValueError("distinct BRAM sources share a selector codeword")
            codeword_sources[codeword] = source
            routes.append(BramRoute(source, destination, row["pip_type"], row["cfg_group"], clear, sets))
    return tuple(routes)


def load_routes(chipdb_root):
    routes = _load_routes(chipdb_root, TABLE) + _load_routes(chipdb_root, CORRIDOR_TABLE)
    edges, codewords = set(), {}
    for route in routes:
        edge = (route.source, route.destination)
        if edge in edges:
            raise ValueError("duplicate BRAM route across tables")
        edges.add(edge)
        key = (route.destination, route.config, frozenset(route.set_bits))
        if key in codewords and codewords[key] != route.source:
            raise ValueError("distinct BRAM sources share a selector codeword across tables")
        codewords[key] = route.source
    return routes
