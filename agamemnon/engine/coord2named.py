#!/usr/bin/env python3
"""Project Agamemnon GATE — the reliable COORD/ID -> NAMED routing-node mapper.

GATE FINDING (see gate_findings.md):
  * alta::dump_route_coord_cmd emits PLACEMENT coords `(x y n)` where n is a per-tile
    SLICE/LE index (0..7) -- NOT a routing-resource node. It is useless for the RRG.
  * The RELIABLE node identity used by route.tx is the triple it prints on every node line:
        <tiletype_code>:<nodetype>:#<localid>  "<TILE>(x,y):<resource>"
    This triple matches tools/agamemnon/wires.csv EXACTLY (50046/50046, 0 mismatch).
  * So the "coord->named" map is really (tiletype_code, nodetype, localid) -> named node,
    and route.tx already carries the named string inline, so the RRG comes straight from
    route.tx path edges (the FALLBACK), with wires.csv as the canonical node table.

This module loads wires.csv as the canonical node table and parses any decoded route.tx into
named directed routing edges using the full-triple node identity (fixes the bare-#id collision
bug in route_parse.py, where #id alone is ~3x ambiguous).
"""
import os, re, csv, collections

HERE  = os.path.dirname(os.path.abspath(__file__))
WIRES = os.path.join(os.path.dirname(HERE), "chipdb", "wires.csv")

# Node line in route.tx (both the global "Nodes :" section and per-net paths):
#   <tt>:<nt>:#<localid> "<TILE>(x,y):<resource>"   [optional trailing fields]
NODE = re.compile(r'(\d+):(\d+):#(\d+)\s+"([A-Za-z]+TILE)\((\d+),(\d+)\):([A-Za-z_0-9]+)"')


def load_wires(path=WIRES):
    """Canonical node table: (tiletype_code,nodetype,localid) -> (x,y,tile,resource)."""
    t = {}
    for r in csv.DictReader(open(path)):
        t[(int(r["tiletype_code"]), int(r["nodetype"]), int(r["localid"]))] = (
            int(r["x"]), int(r["y"]), r["tile"], r["resource"])
    return t


def named(key, wires=None):
    """key=(tiletype_code,nodetype,localid) -> 'TILE(x,y):resource' (the canonical name)."""
    if wires is None:
        wires = load_wires()
    x, y, tile, res = wires[key]
    return f"{tile}({x},{y}):{res}"


def parse_route_edges(decoded_txt):
    """Parse a DECODED route.tx string -> (nodes, edges).
      nodes: (tt,nt,localid) -> (x,y,tile,resource)   (from the global 'Nodes :' section)
      edges: set of (src_key, dst_key) directed routing edges from per-net path lists.
    Node identity is the FULL TRIPLE (tt,nt,localid); the bare #id is NOT unique.
    """
    lines = decoded_txt.splitlines()
    ni = next((i for i, l in enumerate(lines) if l.strip().startswith("Nodes :")), len(lines))
    nodes = {}
    for l in lines[ni + 1:]:
        m = NODE.match(l.strip())
        if m:
            nodes[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = (
                int(m.group(5)), int(m.group(6)), m.group(4), m.group(7))
    edges = set()
    section = None
    path = []

    def flush():
        for a, b in zip(path, path[1:]):
            if a != b:
                edges.add((a, b))

    for l in lines[:ni]:
        s = l.strip()
        if s.startswith("net :"):
            section = None; path = []
        elif s.startswith("path :"):
            section = "path"; path = []
        elif s.startswith("steiner"):
            flush(); section = "other"
        elif s.startswith(("segment", "reached")):
            section = "other"
        m = NODE.match(s)
        if m and section == "path":
            path.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return nodes, edges


if __name__ == "__main__":
    import sys
    from agamemnon.engine import tx_decode
    # self-test only: pass a decoded route.tx path as argv[1], or set $AGAMEMNON_ROUTE_TX;
    # the trailing relative path is a dev fallback (not shipped).
    rt = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGAMEMNON_ROUTE_TX")) or os.path.join(
        os.path.dirname(HERE), "cpld_native2", "alta_db", "route.tx")
    txt = tx_decode.decode_tx(rt).decode("latin1")
    wires = load_wires()
    nodes, edges = parse_route_edges(txt)
    ok = sum(1 for a, b in edges if a in wires and b in wires)
    print(f"global Nodes: {len(nodes)};  named edges: {len(edges)};  resolvable in wires.csv: {ok}/{len(edges)}")
    fam = lambda k: wires.get(k, (0, 0, "?", "?"))[3].rstrip("0123456789")
    for k, c in collections.Counter((fam(a), fam(b)) for a, b in edges).most_common(10):
        print(f"  {k[0]:>10} -> {k[1]:<10} {c}")
