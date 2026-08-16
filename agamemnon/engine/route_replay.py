#!/usr/bin/env python3
"""Fail-closed exact route replay for an isomorphic qualified netlist.

This is intentionally narrower than routing.  The source netlist must have the
same primitive types, parameters, ports, and complete producer/consumer graph
as the routed checkpoint.  Net names and numeric JSON bit IDs may differ.  Only
after proving that isomorphism do we copy each checkpoint BEL and ROUTING string
onto the source namespace.

No functional parameter changes are accepted here.  A modified design needs a
separate, reviewed qualification composer rather than silently inheriting the
checkpoint's hardware claim.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path


class ReplayError(ValueError):
    """The source is not exactly isomorphic to the routed checkpoint."""


def _physical_attributes(attributes):
    """Return attributes that can influence agrv2k placement/packing/emission."""
    return {key: value for key, value in attributes.items()
            if key.startswith("AGRV2K_")}


def _validate_route(route, name):
    fields = route.split(";")
    if len(fields) % 3:
        raise ReplayError("checkpoint route is malformed: %s" % name)
    roots = 0
    for destination, pip, strength in zip(fields[0::3], fields[1::3],
                                          fields[2::3]):
        if not destination or not strength:
            raise ReplayError("checkpoint route has an empty field: %s" % name)
        if pip:
            if pip.count(".") != 1 or pip.split(".", 1)[1] != destination:
                raise ReplayError("checkpoint route pip/destination mismatch: %s" %
                                  name)
        else:
            roots += 1
    if roots != 1:
        raise ReplayError("checkpoint route requires exactly one root: %s" % name)


def _load(path: Path):
    design = json.loads(path.read_text(encoding="utf-8"))
    modules = design.get("modules", {})
    if "top" not in modules:
        raise ReplayError("exact route replay requires a module named top")
    return design, modules["top"]


def _endpoints(top, cell_names=None):
    result = defaultdict(list)
    for port_name, port in top.get("ports", {}).items():
        for index, bit in enumerate(port.get("bits", [])):
            if isinstance(bit, int):
                result[bit].append(("top", port_name, port["direction"], index))
    cell_names = cell_names or {name: name for name in top.get("cells", {})}
    for cell_name, cell in top.get("cells", {}).items():
        canonical_name = cell_names[cell_name]
        directions = cell.get("port_directions", {})
        for port_name, bits in cell.get("connections", {}).items():
            if port_name not in directions:
                raise ReplayError("%s.%s lacks port direction" %
                                  (cell_name, port_name))
            for index, bit in enumerate(bits):
                if isinstance(bit, int):
                    result[bit].append(
                        ("cell", canonical_name, port_name,
                         directions[port_name], index))
    return {bit: tuple(sorted(items)) for bit, items in result.items()}


def _named_nets(top, endpoint_map):
    result = {}
    for name, net in top.get("netnames", {}).items():
        bits = net.get("bits", [])
        # Yosys may retain a label for an intentionally unconnected primitive
        # input as the single sentinel ``x``.  It has no physical route and is
        # compared later through the owning cell-port connectivity.
        if bits == ["x"]:
            continue
        if len(bits) != 1 or not isinstance(bits[0], int):
            raise ReplayError("exact replay requires one integer bit per net: %s" %
                              name)
        signature = endpoint_map.get(bits[0], ())
        if not signature:
            raise ReplayError("net %s has no endpoints" % name)
        if signature in result:
            raise ReplayError("ambiguous endpoint signature for %s and %s" %
                              (result[signature], name))
        result[signature] = name
    return result


def _logical_value(value, endpoint_map, named_bits):
    if isinstance(value, int):
        signature = endpoint_map.get(value, ())
        if (value not in named_bits and len(signature) == 1 and
                signature[0][0] == "cell"):
            return ("unconnected", "x")
        return ("net", signature)
    if value == "x":
        return ("unconnected", "x")
    return ("constant", value)


def _cell_mapping(source_cells, checkpoint_cells):
    mapping = {name: name for name in set(source_cells) & set(checkpoint_cells)}
    source_extra = sorted(set(source_cells) - set(mapping))
    checkpoint_extra = sorted(set(checkpoint_cells) - set(mapping.values()))

    def fingerprint(cell):
        return cell["type"], tuple(sorted(cell.get("parameters", {}).items()))

    checkpoint_by_fingerprint = defaultdict(list)
    for name in checkpoint_extra:
        checkpoint_by_fingerprint[fingerprint(checkpoint_cells[name])].append(name)
    for name in source_extra:
        matches = checkpoint_by_fingerprint[fingerprint(source_cells[name])]
        if len(matches) != 1:
            raise ReplayError("cannot uniquely map renamed cell %s: %s" %
                              (name, matches))
        mapping[name] = matches.pop()
    if set(mapping.values()) != set(checkpoint_cells):
        raise ReplayError("cell mapping is not bijective")
    return mapping


def replay(source_design, checkpoint_design):
    source = source_design["modules"]["top"]
    checkpoint = checkpoint_design["modules"]["top"]
    source_cells = source.get("cells", {})
    checkpoint_cells = checkpoint.get("cells", {})
    cell_map = _cell_mapping(source_cells, checkpoint_cells)

    bel_owners = defaultdict(list)
    for name, cell in checkpoint_cells.items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            raise ReplayError("checkpoint cell lacks BEL: %s" % name)
        bel_owners[bel].append(name)
    duplicate_bels = {bel: names for bel, names in bel_owners.items()
                      if len(names) > 1}
    if duplicate_bels:
        raise ReplayError("checkpoint assigns duplicate BELs: %s" % duplicate_bels)

    source_endpoints = _endpoints(source, cell_map)
    checkpoint_endpoints = _endpoints(checkpoint)
    source_nets = _named_nets(source, source_endpoints)
    checkpoint_nets = _named_nets(checkpoint, checkpoint_endpoints)
    if set(source_nets) != set(checkpoint_nets):
        raise ReplayError("producer/consumer net signature set differs")

    if set(source.get("ports", {})) != set(checkpoint.get("ports", {})):
        raise ReplayError("top-level port names differ")
    for name in source.get("ports", {}):
        left = source["ports"][name]
        right = checkpoint["ports"][name]
        if (left["direction"] != right["direction"] or
                len(left["bits"]) != len(right["bits"])):
            raise ReplayError("top port differs: %s" % name)

    source_named_bits = {
        bit for net in source.get("netnames", {}).values()
        for bit in net.get("bits", []) if isinstance(bit, int)
    }
    checkpoint_named_bits = {
        bit for net in checkpoint.get("netnames", {}).values()
        for bit in net.get("bits", []) if isinstance(bit, int)
    }
    for source_name in sorted(source_cells):
        name = cell_map[source_name]
        left = source_cells[source_name]
        right = checkpoint_cells[name]
        if left["type"] != right["type"]:
            raise ReplayError("cell type differs: %s" % name)
        if left.get("parameters", {}) != right.get("parameters", {}):
            raise ReplayError("cell parameters differ: %s" % name)
        left_physical = _physical_attributes(left.get("attributes", {}))
        right_physical = _physical_attributes(right.get("attributes", {}))
        unexpected = {key: value for key, value in left_physical.items()
                      if right_physical.get(key) != value}
        if unexpected:
            raise ReplayError("source physical attributes differ: %s %s" %
                              (name, unexpected))
        for port in (set(left.get("port_directions", {})) |
                     set(right.get("port_directions", {}))):
            left_direction = left.get("port_directions", {}).get(port)
            right_direction = right.get("port_directions", {}).get(port)
            if (left_direction != right_direction and
                    (left.get("connections", {}).get(port) or
                     right.get("connections", {}).get(port))):
                raise ReplayError("cell port directions differ: %s.%s" %
                                  (name, port))
        for port in (set(left.get("connections", {})) |
                     set(right.get("connections", {}))):
            left_bits = left.get("connections", {}).get(port, [])
            right_bits = right.get("connections", {}).get(port, [])
            left_signature = tuple(
                _logical_value(bit, source_endpoints, source_named_bits)
                for bit in left_bits)
            right_signature = tuple(
                _logical_value(bit, checkpoint_endpoints, checkpoint_named_bits)
                for bit in right_bits)
            if left_signature != right_signature:
                raise ReplayError("connectivity differs: %s.%s" % (name, port))

    result = copy.deepcopy(source_design)
    result_top = result["modules"]["top"]
    for source_name, cell in result_top["cells"].items():
        name = cell_map[source_name]
        reference = checkpoint_cells[name]
        attributes = reference.get("attributes", {})
        bel = attributes.get("NEXTPNR_BEL")
        target_attributes = cell.setdefault("attributes", {})
        for key in list(target_attributes):
            if key.startswith("AGRV2K_"):
                del target_attributes[key]
        target_attributes["NEXTPNR_BEL"] = bel
        if "BEL_STRENGTH" in attributes:
            target_attributes["BEL_STRENGTH"] = attributes["BEL_STRENGTH"]
        for key, value in _physical_attributes(attributes).items():
            target_attributes[key] = value
    for signature, source_name in source_nets.items():
        checkpoint_name = checkpoint_nets[signature]
        route = (checkpoint["netnames"][checkpoint_name]
                 .get("attributes", {}).get("ROUTING"))
        if not route:
            raise ReplayError("checkpoint net lacks ROUTING: %s" % checkpoint_name)
        _validate_route(route, checkpoint_name)
        result_top["netnames"][source_name].setdefault("attributes", {})[
            "ROUTING"] = route
    return result, len(source_cells), len(source_nets)


def replay_files(source_path: Path, checkpoint_path: Path, output_path: Path):
    source_design, _source = _load(source_path)
    checkpoint_design, _checkpoint = _load(checkpoint_path)
    result, cells, nets = replay(source_design, checkpoint_design)
    encoded = (json.dumps(result, indent=2) + "\n").encode("utf-8")
    output_path.write_bytes(encoded)
    return cells, nets, hashlib.sha256(encoded).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path,
                        help="synthesized and Qin-packed logical JSON")
    parser.add_argument("checkpoint", type=Path,
                        help="exact routed qualification checkpoint")
    parser.add_argument("output", type=Path,
                        help="routed JSON in the source net namespace")
    args = parser.parse_args()
    try:
        cells, nets, digest = replay_files(args.source, args.checkpoint,
                                           args.output)
    except (OSError, KeyError, json.JSONDecodeError, ReplayError) as exc:
        raise SystemExit("exact route replay rejected: %s" % exc)
    print("exact route replay verified cells=%d nets=%d sha256=%s" %
          (cells, nets, digest))


if __name__ == "__main__":
    main()
