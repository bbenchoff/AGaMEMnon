#!/usr/bin/env python3
"""Extract sensitized four-site BRAM read trees from decoded vendor routing.

The retained silicon oracle drove AHB HADDR[10:2], clocked all four x18
Port-A arrays, and observed HRDATA[31:0] over all 512 addresses.  This tool
selects only those live nets from a decoded ``route.tx`` and preserves their
segment boundaries.  It does not treat unrelated vendor-observed routing as a
conduction claim.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

try:
    from tools.harvest_bram_site_corpus import NODE_PARTS_RE, NODE_RE, normalize_net
except ModuleNotFoundError:  # direct ``python tools/...py`` execution
    from harvest_bram_site_corpus import NODE_PARTS_RE, NODE_RE, normalize_net


HEADER = ["class", "net", "segment", "hop", "src_wire", "dst_wire"]


def canonical_wire(node: str) -> str:
    match = NODE_PARTS_RE.fullmatch(node)
    if match is None:
        raise ValueError(f"malformed routed node {node!r}")
    _tile, x, y, resource = match.groups()
    return f"X{x}Y{y}_{resource}"


def selected_class(name: str) -> str | None:
    if re.fullmatch(r"mem_ahb_haddr\[(?:[2-9]|10)\]", name):
        return "address"
    if re.fullmatch(r"mem_ahb_hrdata\[(?:[0-9]|[12][0-9]|3[01])\]", name):
        return "data"
    if name == "sys_gck":
        return "clock"
    return None


def extract(path: Path) -> list[tuple[object, ...]]:
    text = path.read_text(encoding="latin1")
    rows: list[tuple[object, ...]] = []
    found: set[str] = set()
    for block in re.split(r"\n net : ", text)[1:]:
        name_match = re.match(r'#\d+ - "([^"]+)"', block)
        if not name_match:
            continue
        name = normalize_net(name_match.group(1))
        kind = selected_class(name)
        if kind is None:
            continue
        found.add(name)
        path_match = re.search(
            r"\bpath\b\s*:\s*(\d+)(.*?)(?:\n\s*steiner\b|\Z)", block, re.S
        )
        segment_match = re.search(
            r"\bsegment\b\s*:\s*(\d+)(.*?)(?:\n\s*reached\b|\Z)", block, re.S
        )
        steiner_match = re.search(
            r"\bsteiner\b\s*:\s*(\d+)(.*?)(?:\n\s*segment\b|\Z)", block, re.S
        )
        if path_match is None or segment_match is None or steiner_match is None:
            raise ValueError(f"{path}: selected net {name!r} has no path/segment table")
        nodes = NODE_RE.findall(path_match.group(2))
        steiners = NODE_RE.findall(steiner_match.group(2))
        declared_nodes = int(path_match.group(1))
        lengths = [
            int(value) for value in re.findall(
                r"^\s*(\d+)\s*$", segment_match.group(2), re.M
            )
        ]
        if (len(nodes) != declared_nodes or len(lengths) != int(segment_match.group(1)) or
                len(steiners) != int(steiner_match.group(1)) or
                len(steiners) != len(lengths)):
            raise ValueError(f"{path}: malformed selected route for {name!r}")
        if sum(lengths) != len(nodes):
            raise ValueError(f"{path}: segment table does not partition {name!r}")
        offset = 0
        for segment, length in enumerate(lengths):
            branch = nodes[offset:offset + length]
            offset += length
            # route.tx records the already-routed branch point separately in
            # the parallel steiner table.  It is the predecessor of this
            # segment's first path node.  Segment zero starts at the hard BEL
            # pin and names the hard cell as its steiner; that is not a pip.
            if (segment > 0 and branch and steiners[segment] != branch[0] and
                    ":alta_" not in steiners[segment]):
                rows.append((kind, name, segment, -1,
                             canonical_wire(steiners[segment]),
                             canonical_wire(branch[0])))
            for hop, (source, destination) in enumerate(zip(branch, branch[1:])):
                if source != destination:
                    rows.append((kind, name, segment, hop,
                                 canonical_wire(source), canonical_wire(destination)))

    expected = {f"mem_ahb_haddr[{bit}]" for bit in range(2, 11)}
    expected |= {f"mem_ahb_hrdata[{bit}]" for bit in range(32)}
    expected.add("sys_gck")
    missing = sorted(expected - found)
    if missing:
        raise ValueError(f"{path}: missing selected nets: {missing}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decoded_route", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = extract(args.decoded_route)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"wrote {len(rows)} sensitized path hops -> {args.output}")


if __name__ == "__main__":
    main()
