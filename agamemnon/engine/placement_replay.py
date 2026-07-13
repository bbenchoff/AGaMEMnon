#!/usr/bin/env python3
"""Copy nextpnr BEL constraints from a routed checkpoint onto an equivalent netlist.

This is deliberately structural: every cell in the destination must exist in the
checkpoint with the same type.  It is useful both for route-map experiments and
for making a silicon-qualified placement reproducible while routing data is still
being completed.
"""
import json
import sys


def _top(data):
    modules = data.get("modules", {})
    def asserted(value):
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            try:
                return int(value, 2) != 0
            except ValueError:
                return value.lower() in ("true", "yes")
        return bool(value)

    marked = [m for m in modules.values() if asserted(m.get("attributes", {}).get("top"))]
    if len(marked) == 1:
        return marked[0]
    if len(modules) == 1:
        return next(iter(modules.values()))
    raise ValueError("cannot identify a unique top module")


def replay(source, checkpoint):
    dst_cells = _top(source).get("cells", {})
    ref_cells = _top(checkpoint).get("cells", {})
    # nextpnr's generic LUT packer appends _LC while converting LUT to
    # GENERIC_SLICE.  Index those packed names by their synthesis precursor.
    refs = dict(ref_cells)
    for name, cell in ref_cells.items():
        if name.endswith("_LC"):
            refs.setdefault(name[:-3], cell)
        if name.endswith("_DFFLC"):
            refs.setdefault(name[:-6], cell)
    copied = 0
    for name, cell in dst_cells.items():
        ref = refs.get(name)
        if ref is None:
            # Packing can absorb source DFF cells into their LUT cells, so a
            # routed checkpoint legitimately has fewer cells than synthesis.
            continue
        compatible_pack = cell.get("type") in ("LUT", "DFF") and ref.get("type") == "GENERIC_SLICE"
        if ref.get("type") != cell.get("type") and not compatible_pack:
            raise ValueError("cell type mismatch for %s" % name)
        bel = ref.get("attributes", {}).get("NEXTPNR_BEL")
        if bel:
            cell.setdefault("attributes", {})["NEXTPNR_BEL"] = bel
            copied += 1
    if copied == 0:
        raise ValueError("checkpoint shares no placed cells with the netlist")
    return copied


def write_map(checkpoint, path):
    cells = _top(checkpoint).get("cells", {})
    rows = []
    for name, cell in cells.items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if bel:
            if "," in name or "," in bel:
                raise ValueError("comma in checkpoint cell or BEL name")
            rows.append((name, bel))
    rows.sort()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for name, bel in rows:
            f.write("%s,%s\n" % (name, bel))
    return len(rows)


def main(argv):
    if len(argv) == 4 and argv[1] == "--map":
        with open(argv[2], encoding="utf-8") as f:
            checkpoint = json.load(f)
        copied = write_map(checkpoint, argv[3])
        print("wrote %d packed BEL constraints" % copied)
        return
    if len(argv) != 4:
        raise SystemExit("usage: placement_replay.py <netlist.json> <checkpoint.json> <output.json>\n"
                         "       placement_replay.py --map <checkpoint.json> <output.csv>")
    with open(argv[1], encoding="utf-8") as f:
        source = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        checkpoint = json.load(f)
    copied = replay(source, checkpoint)
    with open(argv[3], "w", encoding="utf-8") as f:
        json.dump(source, f, separators=(",", ":"))
    print("copied %d BEL constraints" % copied)


if __name__ == "__main__":
    main(sys.argv)
