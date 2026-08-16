#!/usr/bin/env python3
"""Harvest a multi-site BRAM placement/routing corpus from decoded vendor output.

This tool deliberately consumes *decoded* ``route.tx`` text.  The proprietary
router, its encoded intermediates, and the decoder data are research inputs and
are not part of the release.  The emitted CSVs contain only derived physical
facts used by the open architecture:

* one BRAM BEL pin map row per observed site; and
* routed edges touching a BramTILE, merged with the existing release graph.

Each ``--oracle`` is ``ROUTED_V,DECODED_ROUTE``.  A complete four-site corpus
must observe every pin in ``--base-bel`` at every requested site.  The command
fails closed on a missing or conflicting terminal instead of assuming that the
four BramTILEs are symmetric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


BEL_HEADER = ["port", "bit", "x", "y", "res"]
EDGE_HEADER = [
    "src_tile", "src_x", "src_y", "src_res",
    "dst_tile", "dst_x", "dst_y", "dst_res",
]
OUTPUT_PORTS = {"DataOutA", "DataOutB"}
NODE_RE = re.compile(r'"([A-Za-z]+TILE\(\d+,\d+\):[^"\s]+)"')
NODE_PARTS_RE = re.compile(r"([A-Za-z]+)TILE\((\d+),(\d+)\):(.+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_vector(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    return [item.strip() for item in value.split(",")]


def normalize_net(value: str) -> str:
    value = value.strip()
    if value.startswith("\\"):
        value = value[1:]
    while value.startswith("!") or value.startswith("~"):
        value = value[1:].strip()
    return re.sub(r"\s+\[", "[", value)


def parse_cells(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    cells: list[dict[str, object]] = []
    pattern = re.compile(r"alta_bram9k\s+(\\?\S+)\s*\((.*?)\)\s*;", re.S)
    for match in pattern.finditer(text):
        instance = match.group(1)
        ports: dict[str, list[str]] = {}
        for port in re.finditer(r"\.(\w+)\(\s*(.*?)\s*\)\s*(?:,|$)", match.group(2), re.S):
            ports[port.group(1)] = split_vector(port.group(2))
        coord = {}
        for axis in "xyz":
            cm = re.search(
                r"defparam\s+%s\s+\.coord_%s\s*=\s*(\d+)\s*;"
                % (re.escape(instance), axis),
                text,
            )
            if not cm:
                raise ValueError(f"{path}: missing coord_{axis} for {instance}")
            coord[axis] = int(cm.group(1))
        cells.append({"instance": instance, "ports": ports, **coord})
    if not cells:
        raise ValueError(f"{path}: no alta_bram9k cells")
    return cells


def parse_route(path: Path) -> tuple[dict[str, set[str]], set[tuple[str, ...]]]:
    text = path.read_text(encoding="latin1")
    nets: dict[str, set[str]] = {}
    edges: set[tuple[str, ...]] = set()
    for block in re.split(r"\n net : ", text)[1:]:
        name_match = re.match(r'#\d+ - "([^"]+)"', block)
        if not name_match:
            continue
        name = normalize_net(name_match.group(1))
        nets.setdefault(name, set()).update(NODE_RE.findall(block))
        path_match = re.search(
            r"\bpath\b\s*:\s*(\d+)(.*?)(?:\n\s*steiner\b|\Z)", block, re.S
        )
        if not path_match:
            continue
        expected_nodes = int(path_match.group(1))
        nodes = NODE_RE.findall(path_match.group(2))
        if len(nodes) != expected_nodes:
            raise ValueError(
                f"{path}: net {name!r} declares {expected_nodes} path nodes, "
                f"decoded {len(nodes)}"
            )
        segment_match = re.search(
            r"\bsegment\b\s*:\s*(\d+)(.*?)(?:\n\s*reached\b|\Z)", block, re.S
        )
        lengths = []
        if segment_match:
            expected_segments = int(segment_match.group(1))
            lengths = [
                int(value) for value in re.findall(
                    r"^\s*(\d+)\s*$", segment_match.group(2), re.M
                )
            ]
            if len(lengths) != expected_segments or sum(lengths) != len(nodes):
                raise ValueError(
                    f"{path}: net {name!r} segment table {lengths} does not "
                    f"partition {len(nodes)} path nodes"
                )
        elif nodes:
            lengths = [len(nodes)]
        offset = 0
        for length in lengths:
            segment = nodes[offset:offset + length]
            offset += length
            for source, destination in zip(segment, segment[1:]):
                if "BramTILE" not in source and "BramTILE" not in destination:
                    continue
                src = NODE_PARTS_RE.fullmatch(source)
                dst = NODE_PARTS_RE.fullmatch(destination)
                if src and dst and source != destination:
                    edges.add(src.groups() + dst.groups())
    return nets, edges


def load_rows(path: Path, header: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or list(rows[0]) != header:
        raise ValueError(f"{path}: expected header {header}")
    return rows


def write_rows(path: Path, header: list[str], rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def net_for_pin(ports: dict[str, list[str]], port: str, bit: int) -> str | None:
    values = ports.get(port)
    if values is None or bit >= len(values):
        return None
    token = normalize_net(values[len(values) - 1 - bit])
    if token in {"gnd", "vcc"} or "'" in token:
        return None
    return token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-bel", type=Path, required=True)
    parser.add_argument("--base-edges", type=Path, required=True)
    parser.add_argument(
        "--oracle", action="append", required=True,
        help="ROUTED_V,DECODED_ROUTE (repeat for each output window)",
    )
    parser.add_argument("--sites", default="13,1;13,2;13,3;13,4")
    parser.add_argument("--output-bel", type=Path, required=True)
    parser.add_argument("--output-edges", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    sites = {
        tuple(int(part) for part in item.split(","))
        for item in args.sites.split(";") if item
    }
    base_bel = load_rows(args.base_bel, BEL_HEADER)
    templates = {
        (row["port"], int(row["bit"])): row["res"] for row in base_bel
    }
    if len(templates) != len(base_bel):
        raise ValueError("base BEL contains duplicate logical pins")

    observed: set[tuple[str, int, int, int, str]] = set()
    all_edges: set[tuple[str, ...]] = {
        tuple(row[column] for column in EDGE_HEADER)
        for row in load_rows(args.base_edges, EDGE_HEADER)
    }
    sources = []
    placed_sites: set[tuple[int, int]] = set()

    for specification in args.oracle:
        try:
            routed_name, decoded_name = specification.split(",", 1)
        except ValueError as exc:
            raise ValueError(f"bad --oracle {specification!r}") from exc
        routed = Path(routed_name)
        decoded = Path(decoded_name)
        cells = parse_cells(routed)
        nets, edges = parse_route(decoded)
        all_edges.update(edges)
        for cell in cells:
            xy = (int(cell["x"]), int(cell["y"]))
            if xy not in sites:
                raise ValueError(f"{routed}: unexpected BRAM placement {xy}")
            placed_sites.add(xy)
            ports = cell["ports"]
            assert isinstance(ports, dict)
            for (port, bit), resource in templates.items():
                net = net_for_pin(ports, port, bit)
                if net is None or net not in nets:
                    continue
                expected = f"BramTILE({xy[0]},{xy[1]}):{resource}"
                if expected in nets[net]:
                    observed.add((port, bit, xy[0], xy[1], resource))
                    continue
                at_site = sorted(
                    node for node in nets[net]
                    if node.startswith(f"BramTILE({xy[0]},{xy[1]}):")
                )
                # An unconnected output leaves an internal net with no route.
                if port in OUTPUT_PORTS and not at_site:
                    continue
                raise ValueError(
                    f"{routed}: {cell['instance']} {port}[{bit}] net {net!r} "
                    f"does not reach expected {expected}; site nodes={at_site}"
                )
        sources.append({
            "routed_sha256": sha256(routed),
            "decoded_route_sha256": sha256(decoded),
            "bram_cells": len(cells),
            "derived_bram_edges": len(edges),
        })

    expected = {
        (port, bit, x, y, resource)
        for (port, bit), resource in templates.items()
        for x, y in sites
    }
    missing = sorted(expected - observed)
    if placed_sites != sites:
        raise ValueError(f"placed sites {sorted(placed_sites)} != requested {sorted(sites)}")
    if missing:
        preview = ", ".join(str(item) for item in missing[:12])
        raise ValueError(f"corpus is missing {len(missing)} BEL pins: {preview}")

    bel_rows = sorted(observed, key=lambda row: (row[2], row[3], row[0], row[1]))
    edge_rows = sorted(all_edges, key=lambda row: tuple(
        int(value) if index in {1, 2, 5, 6} else value
        for index, value in enumerate(row)
    ))
    write_rows(args.output_bel, BEL_HEADER, bel_rows)
    write_rows(args.output_edges, EDGE_HEADER, edge_rows)

    result = {
        "schema": 1,
        "sites": [list(site) for site in sorted(sites)],
        "logical_pins_per_site": len(templates),
        "bel_rows": len(bel_rows),
        "merged_bram_edges": len(edge_rows),
        "base_bel_sha256": sha256(args.base_bel),
        "base_edges_sha256": sha256(args.base_edges),
        "sources": sources,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
