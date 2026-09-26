"""Exact routed branches for the qualified X13Y4 TMUX09 write source.

This is a source-to-route profile, not a routed-checkpoint replay.  Placement
and routing first run normally; the measured reset, hard-output, and three
source/observer trees are then replaced atomically with their silicon-qualified
branches before strict bitgen.  The BRAM feature independently verifies the
resulting structure and routes before admitting the two scoped TMUX/KMUX
codewords, and the CLI requires the exact final raw and compressed hashes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .qualified_bram_constant_routes import GROUND_ROUTES


PROFILES = frozenset({
    "bram-tmux9-i0-d1-we0", "bram-tmux9-i0-d1-we1",
    "bram-tmux9-i1-d0-we0", "bram-tmux9-i1-d0-we1",
})

# The hard BRAM output tree is represented in nextpnr's sink-rooted ordering,
# unlike the three ordinary fabric-driver trees below.  It is part of the
# measured simultaneous solution and must remain fixed as h1-h3 are replaced.
H0_ROUTE = (
    "X14Y4_RMUX20;X13Y4_BufMUX01.X14Y4_RMUX20;1;"
    "X10Y4_RMUX74;X14Y4_RMUX20.X10Y4_RMUX74;1;"
    "X14Y4_RMUX02;X10Y4_RMUX74.X14Y4_RMUX02;1;"
    "X14Y8_RMUX19;X14Y4_RMUX02.X14Y8_RMUX19;1;"
    "X14Y12_RMUX79;X14Y8_RMUX19.X14Y12_RMUX79;1;"
    "X13Y12_BBMUXE02;X14Y12_RMUX79.X13Y12_BBMUXE02;1;"
    "X0Y5_SinkMUXPseudo02;X13Y12_BBMUXE02.X0Y5_SinkMUXPseudo02;1;"
    "X13Y4_BufMUX01;;1"
)
RESET_LOW_ROUTE = (
    "X14Y5_RMUX80;X13Y5_BufMUX19.X14Y5_RMUX80;1;"
    "X14Y3_RMUX33;X14Y5_RMUX80.X14Y3_RMUX33;1;"
    "X12Y3_RMUX39;X14Y3_RMUX33.X12Y3_RMUX39;1;"
    "X12Y4_RMUX68;X12Y3_RMUX39.X12Y4_RMUX68;1;"
    "X14Y4_RMUX91;X12Y4_RMUX68.X14Y4_RMUX91;1;"
    "X15Y4_RMUX79;X14Y4_RMUX91.X15Y4_RMUX79;1;"
    "X13Y4_RMUX40;X15Y4_RMUX79.X13Y4_RMUX40;1;"
    "X13Y4_IMUX32;X13Y4_RMUX40.X13Y4_IMUX32;1;"
    "X13Y4_TileAsyncMUX00;X13Y4_IMUX32.X13Y4_TileAsyncMUX00;1;"
    "X13Y5_BufMUX19;;1"
)
RESET_HIGH_ROUTE = (
    "X14Y5_RMUX80;X13Y5_BufMUX19.X14Y5_RMUX80;1;"
    "X14Y3_RMUX33;X14Y5_RMUX80.X14Y3_RMUX33;1;"
    "X11Y3_RMUX39;X14Y3_RMUX33.X11Y3_RMUX39;1;"
    "X11Y4_RMUX68;X11Y3_RMUX39.X11Y4_RMUX68;1;"
    "X12Y4_RMUX91;X11Y4_RMUX68.X12Y4_RMUX91;1;"
    "X14Y4_RMUX79;X12Y4_RMUX91.X14Y4_RMUX79;1;"
    "X13Y4_RMUX40;X14Y4_RMUX79.X13Y4_RMUX40;1;"
    "X13Y4_IMUX32;X13Y4_RMUX40.X13Y4_IMUX32;1;"
    "X13Y4_TileAsyncMUX00;X13Y4_IMUX32.X13Y4_TileAsyncMUX00;1;"
    "X13Y5_BufMUX19;;1"
)

H1_COMMON = (
    ("X14Y8_OMUX08", "X14Y8_OMUX06"),
    ("X14Y8_OMUX06", "X15Y8_RMUX02"),
    ("X15Y8_RMUX02", "X15Y12_RMUX03"),
    ("X15Y12_RMUX03", "X14Y12_RMUX20"),
    ("X14Y12_RMUX20", "X13Y12_BBMUXE03"),
    ("X13Y12_BBMUXE03", "X0Y5_SinkMUXPseudo03"),
    ("X14Y8_OMUX06", "X15Y8_RMUX21"),
    ("X15Y8_RMUX21", "X15Y4_RMUX86"),
    ("X15Y4_RMUX86", "X11Y4_RMUX66"),
    ("X11Y4_RMUX66", "X10Y4_IMUX03"),
    ("X14Y8_OMUX08", "X14Y8_RMUX09"),
    ("X14Y8_RMUX09", "X14Y12_RMUX29"),
    ("X14Y12_RMUX29", "X14Y12_IMUX01"),
)
H1_WEA = (
    ("X15Y4_RMUX86", "X13Y4_TMUX09"),
    ("X13Y4_TMUX09", "X13Y4_KMUX03"),
)
H2 = (
    ("X10Y4_OMUX02", "X10Y4_RMUX08"),
    ("X10Y4_RMUX08", "X14Y4_RMUX32"),
    ("X14Y4_RMUX32", "X14Y8_RMUX32"),
    ("X14Y8_RMUX32", "X14Y12_RMUX32"),
    ("X14Y12_RMUX32", "X14Y12_RMUX34"),
    ("X14Y12_RMUX34", "X14Y12_IMUX00"),
    ("X14Y8_RMUX32", "X14Y12_RMUX26"),
    ("X14Y12_RMUX26", "X13Y12_BBMUXE04"),
    ("X13Y12_BBMUXE04", "X0Y5_SinkMUXPseudo04"),
    ("X10Y4_OMUX02", "X10Y4_RMUX15"),
    ("X10Y4_RMUX15", "X14Y4_RMUX69"),
    ("X14Y4_RMUX69", "X14Y8_RMUX77"),
    ("X14Y8_RMUX77", "X14Y8_IMUX11"),
)
H3 = (
    ("X14Y12_OMUX02", "X14Y12_RMUX13"),
    ("X14Y12_RMUX13", "X13Y12_BBMUXE05"),
    ("X13Y12_BBMUXE05", "X0Y5_SinkMUXPseudo05"),
)


def is_high(profile: str) -> bool:
    if profile not in PROFILES:
        raise ValueError("unknown qualified TMUX09 source profile %r" % profile)
    return profile.endswith("we1")


def _route(root: str, edges) -> str:
    fields = [root + ";;5"]
    fields.extend("%s;%s.%s;5" % (dst, src, dst) for src, dst in edges)
    return ";".join(fields)


def expected_routes(profile: str) -> dict[str, str]:
    high = is_high(profile)
    return {
        "resetn": RESET_HIGH_ROUTE if high else RESET_LOW_ROUTE,
        "h0": H0_ROUTE,
        "h1": _route("X14Y8_OMUX08", H1_COMMON + (H1_WEA if high else ())),
        "h2": _route("X10Y4_OMUX02", H2),
        "h3": _route("X14Y12_OMUX02", H3),
    }


def routes_match(module: dict, profile: str) -> bool:
    netnames = module.get("netnames", {})
    return all(
        netnames.get(name, {}).get("attributes", {}).get("ROUTING") == route
        for name, route in expected_routes(profile).items()
    )


DATA_SOURCE_ROUTES = {
    "bram-tmux9-i0-d1-we1": (
        "X14Y4_OMUX41;;1;"
        "X13Y4_IMUX29;X13Y4_RMUX05.X13Y4_IMUX29;5;"
        "X13Y4_RMUX05;X15Y4_RMUX03.X13Y4_RMUX05;5;"
        "X15Y4_RMUX03;X14Y4_RMUX74.X15Y4_RMUX03;5;"
        "X14Y4_RMUX74;X14Y4_OMUX41.X14Y4_RMUX74;5"
    ),
    "bram-tmux9-i1-d0-we1": (
        "X13Y4_IMUX29;X13Y4_RMUX53.X13Y4_IMUX29;5;"
        "X13Y4_RMUX53;X15Y4_RMUX63.X13Y4_RMUX53;5;"
        "X15Y4_RMUX63;X14Y4_RMUX15.X15Y4_RMUX63;5;"
        "X14Y4_RMUX15;X14Y4_OMUX02.X14Y4_RMUX15;5;"
        "X14Y4_OMUX02;;5"
    ),
}


def source_signal_routes(profile: str) -> dict[str, str]:
    """All fixed source-profile signal trees, including live write data."""
    routes = expected_routes(profile)
    if is_high(profile):
        routes["din1"] = DATA_SOURCE_ROUTES[profile]
    return routes


def required_routes(profile: str) -> dict[str, str]:
    """Return every reserved tree, including the explicitly placed zero source."""
    return {**source_signal_routes(profile), "$PACKER_GND_NET": GROUND_ROUTES[profile]}


def required_path_edges() -> list[tuple[str, str]]:
    """Exact graph closure for the four hash-bound source profiles only."""
    edges = set()
    for profile in sorted(PROFILES):
        for route in required_routes(profile).values():
            fields = route.split(";")
            for offset in range(0, len(fields), 3):
                destination, pip = fields[offset:offset + 2]
                if not pip:
                    continue
                source, pip_destination = pip.split(".")
                if destination != pip_destination:
                    raise ValueError("qualified TMUX09 route destination disagrees with pip")
                edges.add((source, destination))
    return sorted(edges)


def _prepare_ground_source(module: dict, profile: str) -> None:
    """Represent the qualified constant's source before native pin placement.

    A generated constant is otherwise free to move, while its qualified route
    has a fixed root. Materialize the same logical zero with that placement and
    route constraint instead of moving a cell after routing.
    """
    route = GROUND_ROUTES[profile]
    fields = route.split(";")
    roots = [fields[i] for i in range(0, len(fields) - 2, 3) if not fields[i + 1]]
    match = re.fullmatch(r"X(\d+)Y(\d+)_OMUX(\d+)", roots[0]) if len(roots) == 1 else None
    if match is None or int(match[3]) % 3 != 2:
        raise ValueError("qualified TMUX09 ground tree must have one F-output root")
    bel = "X%sY%s_SLICE%d" % (match[1], match[2], int(match[3]) // 3)
    cells = module.setdefault("cells", {})
    nets = module.setdefault("netnames", {})
    if "$PACKER_GND" in cells or "$PACKER_GND_NET" in nets:
        raise ValueError("qualified TMUX09 ground name already exists")
    if any(cell.get("attributes", {}).get("BEL") == bel for cell in cells.values()):
        raise ValueError("qualified TMUX09 ground BEL already requested")
    vectors = [bits for cell in cells.values() for bits in cell.get("connections", {}).values()]
    vectors += [net.get("bits", []) for net in nets.values()]
    vectors += [port.get("bits", []) for port in module.get("ports", {}).values()]
    if not any("0" in bits for bits in vectors):
        raise ValueError("qualified TMUX09 source has no constant-zero consumers")
    bit = max((value for bits in vectors for value in bits if isinstance(value, int)), default=1) + 1
    for bits in vectors:
        for index, value in enumerate(bits):
            if value == "0":
                bits[index] = bit
    cells["$PACKER_GND"] = {
        "hide_name": 1, "type": "GENERIC_SLICE",
        "parameters": {"K": "100", "INIT": "0000000000000000", "FF_USED": "0"},
        "attributes": {"BEL": bel, "keep": "1"},
        "port_directions": {"I": "input", "CLK": "input", "F": "output", "Q": "output"},
        "connections": {"I": [], "CLK": [], "F": [bit], "Q": []},
    }
    nets["$PACKER_GND_NET"] = {
        "hide_name": 1, "bits": [bit], "attributes": {"AGAMEMNON_REQUIRED_ROUTE": route},
    }


DATA_SOURCE_BELS = {
    "bram-tmux9-i0-d1-we0": "X19Y6_SLICE10",
    "bram-tmux9-i0-d1-we1": "X14Y4_SLICE13",
    "bram-tmux9-i1-d0-we0": "X19Y6_SLICE10",
    "bram-tmux9-i1-d0-we1": "X14Y4_SLICE0",
}


def _prepare_data_source(module: dict, profile: str) -> None:
    """Bind the retained constant LUT as part of the exact-image contract.

    A constant's unused/constant-folded route does not make its configured LUT
    disappear. Its location must be declared before placement, just like the
    active source and observer cells, for these hash-bound profiles.
    """
    cells = module.get("cells", {})
    cell = cells.get("src_d1", {})
    parameters = cell.get("parameters", {})
    expected = 0xFFFF if profile.startswith("bram-tmux9-i0-d1-") else 0
    try:
        valid = (cell.get("type") == "GENERIC_SLICE"
                 and int(str(parameters["INIT"]), 2) == expected
                 and int(str(parameters["FF_USED"]), 2) == 0
                 and len(cell.get("connections", {}).get("F", [])) == 1)
    except (KeyError, ValueError):
        valid = False
    if not valid:
        raise ValueError("qualified TMUX09 data source is missing or not the expected constant")
    bel = DATA_SOURCE_BELS[profile]
    attributes = cell.setdefault("attributes", {})
    if attributes.get("BEL") not in (None, "", bel):
        raise ValueError("qualified TMUX09 data source BEL disagrees")
    if any(name != "src_d1" and other.get("attributes", {}).get("BEL") == bel
           for name, other in cells.items()):
        raise ValueError("qualified TMUX09 data source BEL already requested")
    attributes["BEL"] = bel


def prepare_route_reservations(path, profile: str) -> None:
    """Carry the required trees into native routing before other nets compete."""
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    modules = document.get("modules", {})
    if "top" not in modules:
        raise ValueError("qualified TMUX09 reservations require a top module")
    nets = modules["top"].get("netnames", {})
    routes = source_signal_routes(profile)
    missing = sorted(set(routes) - set(nets))
    if missing:
        raise ValueError("qualified TMUX09 reservations lost nets: " + ", ".join(missing))
    _prepare_ground_source(modules["top"], profile)
    _prepare_data_source(modules["top"], profile)
    for name, route in routes.items():
        nets[name].setdefault("attributes", {})["AGAMEMNON_REQUIRED_ROUTE"] = route
    source.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")


def _route_wires(route: str) -> set[str]:
    """Return every named wire consumed by a nextpnr ROUTING tree."""
    fields = route.split(";")
    wires = {fields[0]} if fields and fields[0] else set()
    for offset in range(3, len(fields), 3):
        if offset + 1 >= len(fields):
            break
        destination, pip = fields[offset:offset + 2]
        if destination:
            wires.add(destination)
        if "." in pip:
            source, pip_destination = pip.split(".", 1)
            wires.update((source, pip_destination))
    return wires


def canonicalize_routed_file(path, profile: str, *, include_constants: bool = False) -> None:
    """Replace the three qualified trees after proving they are unoccupied."""
    routed = Path(path)
    document = json.loads(routed.read_text(encoding="utf-8"))
    modules = document.get("modules", {})
    if set(modules) != {"top"}:
        raise ValueError("qualified TMUX09 source build requires one top module")
    module = modules["top"]
    netnames = module.get("netnames", {})
    replacement = source_signal_routes(profile) if include_constants else expected_routes(profile)
    missing = sorted(set(replacement) - set(netnames))
    if missing:
        raise ValueError(
            "qualified TMUX09 source build lost routed net(s): %s" %
            ", ".join(missing)
        )
    if include_constants:
        # Fresh builds declare this source and tree before native packing.
        # Verify them again before atomic canonicalization; historical
        # checkpoint canonicalization keeps its existing behavior.
        name = "$PACKER_GND_NET"
        bits = netnames.get(name, {}).get("bits", [])
        drivers = [cell for cell in module.get("cells", {}).values()
                   if cell.get("connections", {}).get("F") == bits and len(bits) == 1]
        if len(drivers) != 1:
            raise ValueError("qualified TMUX09 ground requires one constant driver")
        driver = drivers[0]
        parameters = driver.get("parameters", {})
        bel = driver.get("attributes", {}).get("NEXTPNR_BEL", "")
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
        try:
            constant = (driver.get("type") == "GENERIC_SLICE" and
                        int(str(parameters["INIT"]), 2) == 0 and
                        int(str(parameters["FF_USED"]), 2) == 0)
        except (KeyError, ValueError):
            constant = False
        route = GROUND_ROUTES[profile]
        fields = route.split(";")
        roots = [fields[i] for i in range(0, len(fields) - 2, 3) if not fields[i + 1]]
        expected_root = ("X%sY%s_OMUX%02d" % (match[1], match[2], 3 * int(match[3]) + 2)
                         if match else None)
        if not constant or roots != [expected_root]:
            raise ValueError("qualified TMUX09 ground driver or placed source disagrees")
        if _route_wires(route) & set().union(*map(_route_wires, replacement.values())):
            raise ValueError("qualified TMUX09 ground collides with a required signal tree")
        replacement[name] = route
    qualified_wires = set().union(*map(_route_wires, replacement.values()))
    conflicts = []
    for name, net in netnames.items():
        if name in replacement:
            continue
        route = net.get("attributes", {}).get("ROUTING")
        if not route:
            continue
        overlap = sorted(qualified_wires & _route_wires(route))
        if overlap:
            conflicts.append("%s: %s" % (name, ", ".join(overlap)))
    if conflicts:
        raise ValueError(
            "qualified TMUX09 tree collides with routed net(s): %s" %
            "; ".join(conflicts)
        )
    for name, route in replacement.items():
        netnames[name].setdefault("attributes", {})["ROUTING"] = route
    routed.write_text(
        json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8"
    )
