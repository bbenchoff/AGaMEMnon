"""Fail-closed audit of placed line-0 native-enable control groups.

This is an analysis tool, not an admission mechanism.  It reads the JSON
written by nextpnr and reports whether the current isolated-line-0 contract
was actually realised: each native FF must share a tile with its same-net
control root; that tile may contain combinational LUTs but no other FF class.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


SLICES_PER_TILE = 16
CONTROL_TYPE = "AGRV2K_TILE_CONTROL"
SLICE_TYPE = "GENERIC_SLICE"
ENABLE_ATTR = "AGRV2K_CLOCK_ENABLE_NET"


def _top(document):
    modules = document.get("modules") or {}
    if not modules:
        raise ValueError("document contains no modules")
    return max(modules.values(), key=lambda module: len(module.get("cells") or {}))


def _int(value):
    if isinstance(value, int):
        return value
    return int(str(value), 2) if set(str(value)) <= {"0", "1"} else int(value)


def _tile_and_z(cell):
    bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL")
    if not bel:
        return None, None
    try:
        head, suffix = bel.rsplit("_", 1)
        if not suffix.startswith("SLICE"):
            return None, None
        return head, int(suffix.removeprefix("SLICE"))
    except (ValueError, AttributeError):
        return None, None


def _control_tile(cell):
    bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL")
    if not bel or "_CLKEN" not in bel:
        return None, None
    tile, line = bel.rsplit("_CLKEN", 1)
    try:
        return tile, int(line)
    except ValueError:
        return None, None


def analyze(document):
    module = _top(document)
    roots = collections.defaultdict(list)
    native = collections.defaultdict(list)
    ordinary = collections.defaultdict(list)
    combinational = collections.defaultdict(list)
    tile_enables = collections.defaultdict(set)
    placed_bels = {}
    errors = []

    for name, cell in (module.get("cells") or {}).items():
        attrs = cell.get("attributes") or {}
        params = cell.get("parameters") or {}
        if cell.get("type") == CONTROL_TYPE:
            group = attrs.get(ENABLE_ATTR)
            tile, line = _control_tile(cell)
            if not group or tile is None:
                errors.append("control %s lacks placed line-0 group identity" % name)
            else:
                if line != 0:
                    errors.append("control %s uses unadmitted line %d" % (name, line))
                roots[group].append((tile, name))
            continue
        if cell.get("type") != SLICE_TYPE:
            continue
        tile, z = _tile_and_z(cell)
        if tile is None:
            errors.append("slice %s lacks a placed slice BEL" % name)
            continue
        if not 0 <= z < SLICES_PER_TILE:
            errors.append("slice %s has invalid slot %s" % (name, z))
        if (tile, z) in placed_bels:
            errors.append("slice %s overlaps %s at %s_SLICE%d" %
                          (name, placed_bels[tile, z], tile, z))
        placed_bels[tile, z] = name
        ff_used = _int(params.get("FF_USED", 0))
        group = attrs.get(ENABLE_ATTR)
        if ff_used and group:
            native[group].append((tile, z, name))
            tile_enables[tile].add(group)
        elif ff_used:
            ordinary[tile].append((z, name))
        else:
            combinational[tile].append((z, name))

    group_reports = []
    for tile, enables in sorted(tile_enables.items()):
        if len(enables) > 1:
            errors.append("native tile %s contains different enable groups: %s" %
                          (tile, ", ".join(sorted(enables))))
    for group in roots.keys() - native.keys():
        errors.append("enable %s has control roots but no native members" % group)
    for group in sorted(native):
        members = native[group]
        expected_tiles = (len(members) + SLICES_PER_TILE - 1) // SLICES_PER_TILE
        member_tiles = collections.defaultdict(list)
        for tile, z, name in members:
            member_tiles[tile].append((z, name))
        root_tiles = {tile for tile, _name in roots[group]}
        missing = sorted(set(member_tiles) - root_tiles)
        extra = sorted(root_tiles - set(member_tiles))
        if missing:
            errors.append("enable %s has native members without a same-tile root: %s" %
                          (group, ", ".join(missing)))
        if extra:
            errors.append("enable %s has empty control-root tiles: %s" %
                          (group, ", ".join(extra)))
        if len(root_tiles) != expected_tiles:
            errors.append("enable %s uses %d roots for %d FFs; expected %d at %d FFs/tile" %
                          (group, len(root_tiles), len(members), expected_tiles, SLICES_PER_TILE))
        for tile in sorted(member_tiles):
            if tile in ordinary:
                errors.append("native tile %s for enable %s contains ordinary FFs" % (tile, group))
        group_reports.append({
            "enable": group,
            "native_ffs": len(members),
            "tiles": len(member_tiles),
            "expected_tiles": expected_tiles,
            "member_tiles": {tile: len(value) for tile, value in sorted(member_tiles.items())},
        })

    native_tiles = {tile for group in native.values() for tile, _z, _name in group}
    tile_reports = []
    for tile in sorted(native_tiles):
        used_native = sum(1 for group in native.values() for member in group if member[0] == tile)
        used_comb = len(combinational[tile])
        tile_reports.append({
            "tile": tile,
            "native_ffs": used_native,
            "combinational_slices": used_comb,
            "free_slices": SLICES_PER_TILE - used_native - used_comb,
        })
    return {
        "schema": "agamemnon.native-enable-packing.v1",
        "native_ffs": sum(len(group) for group in native.values()),
        "enable_groups": len(native),
        "control_roots": sum(len(value) for value in roots.values()),
        "groups": group_reports,
        "tiles": tile_reports,
        "errors": errors,
        "valid": not errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="placed nextpnr --write JSON")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = analyze(json.loads(args.json.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
