"""Independent routed-netlist closure for dedicated carry resources.

The C++ uarch owns placement and routing, but image emission must not trust
that mutable state.  This module reconstructs packed carry chains from cell
types, port directions, signal bits, placed BELs, and serialized ``ROUTING``
triples.  Cell names and packer-generated marker strings have no authority.

N5.6A deliberately admits only two native physical families:

* short chains whose complete seeded footprint uses at most nine sites, with
  each chain occupying consecutive slices in one tile; and
* the retained single-chain 25/33-site relative profiles.

Two exact three-site seam checkpoints remain readable as legacy emission
compatibility.  They are not native-placement profiles and do not generalize
their seam, column, or direction.

Every protected carry or ripple-feedback edge is then assigned to its one
semantic owner.  A malformed, missing, extra, or foreign protected edge fails
before any bitstream byte can be changed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re


_BEL = re.compile(r"X(\d+)Y(\d+)_SLICE(\d+)")
_CARRY_WIRE = re.compile(r"X(\d+)Y(\d+)_CARRY(IN|OUT)(\d+)")
_OMUX_WIRE = re.compile(r"X(\d+)Y(\d+)_OMUX(\d+)")
_IMUX_WIRE = re.compile(r"X(\d+)Y(\d+)_IMUX(\d+)")


# The historic partial TFF checkpoint predates the Q-presentation bridge and
# uses one local feedback edge as a same-slice route-through.  It is retained
# only so the CLI can reach (and prove) the existing partial-image refusal; it
# is never emission authority.  Bind that compatibility to the exact parsed
# module so no neighboring route, placement, cell, or metadata change inherits
# the exception.
_LEGACY_PARTIAL_TFF_MODULE_SHA256 = (
    "8a633d51fd19dfa6df62d66349794fd2c962804f6e21948fd6907ed87c069786"
)


class CarryValidationError(ValueError):
    """A routed checkpoint violates the bounded carry contract."""


@dataclass(frozen=True)
class CarrySite:
    x: int
    y: int
    z: int

    @property
    def bel(self):
        return "X%dY%d_SLICE%d" % (self.x, self.y, self.z)


@dataclass(frozen=True)
class ValidatedCarryChain:
    """One name-independent chain, reported with names only for diagnostics."""

    cells: tuple[str, ...]
    sites: tuple[CarrySite, ...]
    roles: tuple[str, ...]
    profile: str
    capture_cells: tuple[str, ...]
    q_feedback_cells: tuple[str, ...]


@dataclass(frozen=True)
class CarryValidationResult:
    chains: tuple[ValidatedCarryChain, ...]
    protected_edges: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _Route:
    edges: frozenset[tuple[str, str]]
    roots: frozenset[str]


@dataclass(frozen=True)
class _CarryCell:
    name: str
    cell: dict
    site: CarrySite
    cin: int | None
    cout: int
    ff_used: int


def _reject(reason):
    raise CarryValidationError("carry route: %s" % reason)


def _module_sha256(module):
    raw = json.dumps(
        module, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _integer_bit(value, what):
    if (not isinstance(value, list) or len(value) != 1 or
            not isinstance(value[0], int) or isinstance(value[0], bool)):
        _reject("%s must be exactly one integer signal bit" % what)
    return value[0]


def _bits(value):
    if not isinstance(value, list):
        return ()
    return tuple(bit for bit in value
                 if isinstance(bit, int) and not isinstance(bit, bool))


def _parameter(cell, name):
    value = (cell.get("parameters") or {}).get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        if all(char in "01" for char in value):
            return int(value, 2)
        return int(value, 0)
    except ValueError:
        return None


def _placed_site(name, cell):
    attrs = cell.get("attributes") or {}
    bel = attrs.get("NEXTPNR_BEL")
    if "BEL" in attrs and attrs["BEL"] != bel:
        _reject("cell %r has conflicting BEL/NEXTPNR_BEL placement" % name)
    match = _BEL.fullmatch(str(bel))
    if match is None:
        _reject("cell %r lacks a valid placed slice NEXTPNR_BEL" % name)
    x, y, z = (int(group) for group in match.groups())
    if not 0 <= z < 16:
        _reject("cell %r is placed at invalid slice index %d" % (name, z))
    return CarrySite(x, y, z)


def _parse_route(value, net_name):
    if value is None:
        return None
    if not isinstance(value, str):
        _reject("net %r has a non-string ROUTING attribute" % net_name)
    text = value.strip()
    if not text:
        return _Route(frozenset(), frozenset())
    fields = text.split(";")
    if len(fields) % 3:
        _reject("net %r ROUTING is not wire/PIP/strength triples" % net_name)
    edges = set()
    roots = set()
    triples = set()
    for wire, pip, strength in zip(fields[0::3], fields[1::3], fields[2::3]):
        if not wire or wire != wire.strip() or pip != pip.strip():
            _reject("net %r ROUTING contains an empty or non-canonical token" % net_name)
        if strength not in {"0", "1", "2", "3", "4", "5", "6"}:
            _reject("net %r ROUTING has invalid strength %r" % (net_name, strength))
        triple = (wire, pip)
        if triple in triples:
            _reject("net %r ROUTING duplicates a wire/PIP triple" % net_name)
        triples.add(triple)
        if not pip:
            if wire in roots:
                _reject("net %r ROUTING duplicates root %s" % (net_name, wire))
            roots.add(wire)
            continue
        if pip.count(".") != 1:
            _reject("net %r ROUTING has malformed PIP %r" % (net_name, pip))
        src, dst = pip.split(".")
        if dst != wire:
            _reject(
                "net %r ROUTING PIP destination %s does not match wire %s" %
                (net_name, dst, wire)
            )
        if (src, dst) in edges:
            _reject("net %r ROUTING duplicates PIP %s" % (net_name, pip))
        edges.add((src, dst))
    return _Route(frozenset(edges), frozenset(roots))


def _routes_by_bit(module):
    routes = {}
    aliases = {}
    netnames = module.get("netnames") or {}
    if not isinstance(netnames, dict):
        _reject("top module netnames is not a mapping")
    for name, net in netnames.items():
        if not isinstance(net, dict):
            _reject("netname %r is not an object" % name)
        attrs = net.get("attributes") or {}
        explicit = "ROUTING" in attrs
        route = _parse_route(attrs.get("ROUTING"), name) if explicit else None
        for bit in _bits(net.get("bits")):
            aliases.setdefault(bit, []).append(name)
            if bit not in routes:
                routes[bit] = route
            elif explicit and routes[bit] is not None and routes[bit] != route:
                _reject(
                    "signal aliases for bit %d disagree about ROUTING (%s)" %
                    (bit, ", ".join(aliases[bit]))
                )
            elif explicit:
                routes[bit] = route
    return routes, aliases


def _signal_ends(module):
    drivers = {}
    users = {}
    cells = module.get("cells") or {}
    for cell_name, cell in cells.items():
        directions = cell.get("port_directions") or {}
        for port, value in (cell.get("connections") or {}).items():
            direction = directions.get(port)
            for bit in _bits(value):
                endpoint = ("cell", cell_name, port)
                if direction in ("output", "inout"):
                    drivers.setdefault(bit, []).append(endpoint)
                if direction in ("input", "inout"):
                    users.setdefault(bit, []).append(endpoint)
    for port_name, port in (module.get("ports") or {}).items():
        direction = port.get("direction")
        for bit in _bits(port.get("bits")):
            endpoint = ("port", port_name, direction)
            # A module input drives the design; a module output consumes it.
            if direction in ("input", "inout"):
                drivers.setdefault(bit, []).append(endpoint)
            if direction in ("output", "inout"):
                users.setdefault(bit, []).append(endpoint)
    return drivers, users


def _live_integer_bits(module):
    """Separate connected signals from nextpnr's anonymous integer holes."""

    named = set()
    for net in (module.get("netnames") or {}).values():
        named.update(_bits((net or {}).get("bits")))
    for port in (module.get("ports") or {}).values():
        named.update(_bits((port or {}).get("bits")))
    occurrences = {}
    for cell in (module.get("cells") or {}).values():
        for value in ((cell or {}).get("connections") or {}).values():
            for bit in _bits(value):
                occurrences[bit] = occurrences.get(bit, 0) + 1
    return named | {bit for bit, count in occurrences.items() if count > 1}


def _carry_wire(wire):
    match = _CARRY_WIRE.fullmatch(wire)
    if match is None:
        return None
    x, y, direction, z = match.groups()
    return int(x), int(y), direction, int(z)


def _protected_carry_wire(wire):
    return _carry_wire(wire) is not None or "_CARRYIN" in wire or "_CARRYOUT" in wire


def _qfb_edge(edge):
    src, dst = edge
    source = _OMUX_WIRE.fullmatch(src)
    destination = _IMUX_WIRE.fullmatch(dst)
    if source is None or destination is None:
        return False
    sx, sy, source_index = (int(group) for group in source.groups())
    dx, dy, destination_index = (int(group) for group in destination.groups())
    if (sx, sy) != (dx, dy) or source_index % 3 != 1:
        return False
    z = source_index // 3
    return 0 <= z < 16 and destination_index == 4 * z + 1


def _carry_edge(before, after):
    src = "X%dY%d_CARRYOUT%02d" % (before.x, before.y, before.z)
    dst = "X%dY%d_CARRYIN%02d" % (after.x, after.y, after.z)
    return src, dst


def _qfb_resources(site):
    q_root = "X%dY%d_OMUX%02d" % (site.x, site.y, 3 * site.z + 2)
    feedback = "X%dY%d_OMUX%02d" % (site.x, site.y, 3 * site.z + 1)
    sink = "X%dY%d_IMUX%02d" % (site.x, site.y, 4 * site.z + 1)
    return q_root, (q_root, feedback), (feedback, sink)


def _profile_sites(count, profile):
    if profile == "legacy-25":
        sites = ([CarrySite(0, 0, z) for z in range(16)] +
                 [CarrySite(0, -1, z) for z in range(9)])
    elif profile == "legacy-33":
        sites = ([CarrySite(0, 0, z) for z in range(16)] +
                 [CarrySite(0, 1, z) for z in range(16)] +
                 [CarrySite(0, -1, 0)])
    else:
        raise AssertionError(profile)
    return tuple(sites[:count])


def _relative_sites(sites):
    root = sites[0]
    return tuple(CarrySite(site.x - root.x, site.y - root.y, site.z)
                 for site in sites)


def _validate_physical_profiles(chains):
    # These two absolute footprints are existing release-strict checkpoints.
    # Keeping them readable preserves byte-identical emission without making
    # either seam available to the N5.6A native short-chain placer.
    retained_seams = {
        (
            CarrySite(10, 4, 14),
            CarrySite(10, 4, 15),
            CarrySite(10, 3, 0),
        ): "retained-seam-x10y4-down",
        (
            CarrySite(15, 2, 14),
            CarrySite(15, 2, 15),
            CarrySite(15, 1, 0),
        ): "retained-seam-x15y2-down",
    }
    if len(chains) == 1:
        exact_sites = tuple(cell.site for cell in chains[0])
        if exact_sites in retained_seams:
            return retained_seams[exact_sites]

    total = sum(len(chain) for chain in chains)
    if total <= 9:
        for chain in chains:
            sites = [cell.site for cell in chain]
            root = sites[0]
            if any((site.x, site.y) != (root.x, root.y) for site in sites):
                _reject("short carry chain crosses a tile boundary")
            expected = list(range(root.z, root.z + len(sites)))
            if root.z + len(sites) > 16 or [site.z for site in sites] != expected:
                _reject("short carry chain is not consecutive in increasing slice order")
        return "short-same-tile"
    if len(chains) != 1:
        _reject("more than nine seeded sites requires one retained legacy chain")
    count = len(chains[0])
    if count <= 25:
        profile = "legacy-25"
    elif count <= 33:
        profile = "legacy-33"
    else:
        _reject("carry chain exceeds the retained 33-site profile")
    if _relative_sites([cell.site for cell in chains[0]]) != _profile_sites(count, profile):
        _reject("carry chain does not match the exact retained %s profile" % profile)
    return profile


def _slice_qfb_claims(module, routes):
    """Return exact semantically owned local slice-feedback resources.

    OMUX[3z+1] -> IMUX[4z+1] is not carry-exclusive: retained HIL-positive
    ordinary slices use the same direct self-Q-to-I[1] resource.  Ownership is
    therefore derived from the placed driving slice and its own I[1] consumer,
    never from the net name or from carry membership.
    """

    claims = {}
    owners = set()
    drivers, _users = _signal_ends(module)
    for name, cell in (module.get("cells") or {}).items():
        if not isinstance(cell, dict) or cell.get("type") != "GENERIC_SLICE":
            continue
        connections = cell.get("connections") or {}
        q_bits = _bits(connections.get("Q"))
        inputs = connections.get("I")
        if len(q_bits) != 1 or not isinstance(inputs, list) or len(inputs) < 2:
            continue
        q_bit = q_bits[0]
        if inputs[1] != q_bit:
            continue
        route = routes.get(q_bit)
        if route is None:
            continue
        routed_qfb = tuple(edge for edge in route.edges if _qfb_edge(edge))
        if not routed_qfb:
            continue
        if _parameter(cell, "FF_USED") != 1:
            _reject("slice %r uses local Q-feedback without FF_USED" % name)
        directions = cell.get("port_directions") or {}
        expected_driver = ("cell", name, "Q")
        if (directions.get("Q") != "output" or directions.get("I") != "input" or
                drivers.get(q_bit, []).count(expected_driver) != 1 or
                any(driver != expected_driver for driver in drivers.get(q_bit, []))):
            _reject("slice %r local Q-feedback lacks one exact Q driver" % name)
        site = _placed_site(name, cell)
        q_root, bridge, qfb = _qfb_resources(site)
        if (routed_qfb != (qfb,) or q_root not in route.roots or
                bridge not in route.edges):
            _reject(
                "slice Q-feedback net bit %d lacks its exact root/bridge/SLICE_QFB path" %
                q_bit
            )
        if qfb in claims and claims[qfb] != q_bit:
            _reject("two slice feedback nets claim one SLICE_QFB PIP")
        claims[qfb] = q_bit
        owners.add(name)
    return claims, owners


def validate_routed_carry(module):
    """Reconstruct and validate all packed carry resources in ``module``.

    The function is intentionally independent of the uarch graph/cache.  It
    proves the serialized artifact that bitgen actually consumes.  An empty
    non-carry design returns an empty result without requiring carry tables.
    """

    if not isinstance(module, dict):
        _reject("top module is not an object")
    if _module_sha256(module) == _LEGACY_PARTIAL_TFF_MODULE_SHA256:
        return CarryValidationResult((), frozenset())
    cells = module.get("cells") or {}
    if not isinstance(cells, dict):
        _reject("top module cells is not a mapping")

    raw_carry = {}
    occupied = {}
    live_bits = _live_integer_bits(module)
    for name, cell in cells.items():
        if not isinstance(cell, dict):
            _reject("cell %r is not an object" % name)
        connections = cell.get("connections") or {}
        has_cin = "CIN" in connections
        has_cout = "COUT" in connections
        if not (has_cin or has_cout):
            continue
        if cell.get("type") != "GENERIC_SLICE":
            _reject("cell %r carries CIN/COUT but is not GENERIC_SLICE" % name)
        if not has_cout:
            _reject("cell %r has CIN without COUT" % name)
        directions = cell.get("port_directions") or {}
        if directions.get("COUT") != "output":
            _reject("cell %r COUT is not declared output" % name)
        if has_cin and directions.get("CIN") != "input":
            _reject("cell %r CIN is not declared input" % name)
        cout = _integer_bit(connections.get("COUT"), "cell %r COUT" % name)
        cin = (_integer_bit(connections.get("CIN"), "cell %r CIN" % name)
               if has_cin else None)
        site = _placed_site(name, cell)
        if site.bel in occupied:
            _reject("carry cells %r and %r duplicate site %s" %
                    (occupied[site.bel], name, site.bel))
        occupied[site.bel] = name
        k = _parameter(cell, "K")
        ff_used = _parameter(cell, "FF_USED")
        init = _parameter(cell, "INIT")
        if k != 4 or ff_used not in (0, 1) or init is None:
            _reject("cell %r has malformed K/FF_USED/INIT carry parameters" % name)
        mode = (cell.get("attributes") or {}).get("AGRV2K_REGISTER_INPUT_MODE")
        expected_mode = "CARRY_SUM_TO_FF" if has_cin and ff_used else "NONE"
        if mode is not None and str(mode) != expected_mode:
            _reject("cell %r has carry/register mode %r, expected %s" %
                    (name, mode, expected_mode))
        if not has_cin:
            if ff_used != 0 or init not in (0x0000, 0x00AA, 0x00FF):
                _reject("seed cell %r has malformed folded/dynamic seed shape" % name)
            if any(_bits(connections.get(port)) for port in ("Q", "F", "CLK")):
                _reject("seed cell %r has active Q/F/CLK state" % name)
            inputs = connections.get("I")
            if not isinstance(inputs, list) or len(inputs) != 4:
                _reject("seed cell %r requires exactly four serialized I pins" % name)
            live_inputs = [index for index, bit in enumerate(inputs)
                           if isinstance(bit, int) and bit in live_bits]
            expected_inputs = [0] if init == 0x00AA else []
            if live_inputs != expected_inputs:
                _reject(
                    "seed cell %r does not match its folded/dynamic I[0] role" % name
                )
        else:
            inputs = connections.get("I")
            if not isinstance(inputs, list) or len(inputs) != 4:
                _reject("carry member %r requires exactly four serialized I pins" % name)
            if (not isinstance(inputs[3], int) or isinstance(inputs[3], bool)):
                _reject("carry member %r lacks its ordinary I[3] D source" % name)
            if ff_used:
                _integer_bit(connections.get("Q"), "registered carry cell %r Q" % name)
                _integer_bit(connections.get("CLK"), "registered carry cell %r CLK" % name)
                if _bits(connections.get("F")):
                    _reject("registered carry cell %r has an active F output" % name)
            else:
                if _bits(connections.get("Q")) or _bits(connections.get("CLK")):
                    _reject("combinational carry cell %r has active Q/CLK state" % name)
                _integer_bit(
                    connections.get("F"), "combinational carry cell %r F" % name
                )
        raw_carry[name] = _CarryCell(name, cell, site, cin, cout, ff_used)

    if not raw_carry:
        # Protected resources remain protected even when the design contains
        # no carry owner.  Slice-local Q feedback is shared with ordinary
        # registered slices, but only the exact same-site Q -> I[1] semantic
        # owner may consume it.
        routes, _aliases = _routes_by_bit(module)
        expected_qfb, _qfb_owners = _slice_qfb_claims(module, routes)
        for bit, route in routes.items():
            if route is None:
                continue
            for edge in route.edges:
                if (_protected_carry_wire(edge[0]) or
                        _protected_carry_wire(edge[1])):
                    _reject("bit %d makes foreign use of carry PIP %s -> %s" %
                            (bit, edge[0], edge[1]))
                if _qfb_edge(edge):
                    if expected_qfb.get(edge) != bit:
                        _reject("bit %d makes foreign use of SLICE_QFB PIP %s -> %s" %
                                (bit, edge[0], edge[1]))
            for root in route.roots:
                if _protected_carry_wire(root):
                    _reject("bit %d makes foreign root use of protected carry wire %s" %
                            (bit, root))
        return CarryValidationResult((), frozenset(expected_qfb))

    # No ordinary cell may occupy a carry footprint, including imported BEL
    # metadata that disagrees with its final NEXTPNR_BEL surface.
    for name, cell in cells.items():
        if name in raw_carry:
            continue
        attrs = cell.get("attributes") or {}
        for key in ("BEL", "NEXTPNR_BEL"):
            if attrs.get(key) in occupied:
                _reject("foreign cell %r also occupies carry site %s" %
                        (name, attrs[key]))

    drivers, users = _signal_ends(module)
    predecessor = {}
    successors = {name: [] for name in raw_carry}
    for name, item in raw_carry.items():
        expected_driver = ("cell", name, "COUT")
        if drivers.get(item.cout, []).count(expected_driver) != 1:
            _reject("cell %r is not the unique declared driver of its COUT bit" % name)
        foreign_drivers = [driver for driver in drivers.get(item.cout, [])
                           if driver != expected_driver]
        if foreign_drivers:
            _reject("cell %r COUT bit has multiple output drivers" % name)
        if item.cin is None:
            continue
        carry_drivers = [other for other in raw_carry.values()
                         if other.cout == item.cin]
        if len(carry_drivers) != 1:
            _reject("carry member %r CIN lacks one direct carry COUT driver" % name)
        before = carry_drivers[0]
        if before.name == name:
            _reject("carry member %r drives its own CIN" % name)
        predecessor[name] = before.name
        successors[before.name].append(name)

    seeds = []
    for name, item in raw_carry.items():
        next_cells = successors[name]
        if len(next_cells) > 1:
            _reject("carry COUT from cell %r branches to multiple CIN users" % name)
        successor_endpoint = (("cell", next_cells[0], "CIN")
                              if next_cells else None)
        external = [endpoint for endpoint in users.get(item.cout, [])
                    if endpoint != successor_endpoint]
        if next_cells and external:
            _reject("interior carry COUT from cell %r has ordinary fanout" % name)
        if item.cin is None:
            if not next_cells:
                _reject("carry seed %r does not drive a first member" % name)
            seeds.append(name)

    chains = []
    seen = set()
    for seed in seeds:
        chain = []
        current = seed
        while current is not None:
            if current in seen:
                _reject("carry graph merges or cycles at cell %r" % current)
            seen.add(current)
            chain.append(raw_carry[current])
            current = successors[current][0] if successors[current] else None
        chains.append(chain)
    if not chains:
        _reject("dedicated carry graph contains no seed")
    if len(seen) != len(raw_carry):
        _reject("dedicated carry graph has untraced members (cycle, merge, or missing seed)")

    # All arithmetic members share the packer's ordinary VCC/F D source.  It
    # is deliberately not a carry-cluster member and may fan out normally.
    d_bits = {
        item.cell["connections"]["I"][3]
        for item in raw_carry.values() if item.cin is not None
    }
    if len(d_bits) != 1:
        _reject("carry members do not share exactly one ordinary I[3] D source")
    d_bit = next(iter(d_bits))
    d_drivers = drivers.get(d_bit, [])
    if len(d_drivers) != 1 or d_drivers[0][0] != "cell":
        _reject("carry I[3] D source lacks one ordinary cell driver")
    _kind, d_name, d_port = d_drivers[0]
    d_cell = cells.get(d_name, {})
    d_connections = d_cell.get("connections") or {}
    if (d_name in raw_carry or d_cell.get("type") != "GENERIC_SLICE" or
            d_port != "F" or "CIN" in d_connections or "COUT" in d_connections):
        _reject("carry I[3] D source is not one ordinary GENERIC_SLICE.F")
    if (_parameter(d_cell, "K") != 4 or _parameter(d_cell, "FF_USED") != 0 or
            _parameter(d_cell, "INIT") != 0xFFFF or
            _bits(d_connections.get("F")) != (d_bit,)):
        _reject("carry I[3] D source is not the exact ordinary VCC shape")

    for seed in seeds:
        seed_cell = raw_carry[seed]
        if _parameter(seed_cell.cell, "INIT") != 0x00AA:
            continue
        input_bit = seed_cell.cell["connections"]["I"][0]
        input_drivers = drivers.get(input_bit, [])
        if len(input_drivers) != 1 or input_drivers[0] == ("cell", seed, "COUT"):
            _reject("dynamic carry seed %r lacks one external I[0] driver" % seed)

    profile = _validate_physical_profiles(chains)
    routes, aliases = _routes_by_bit(module)
    expected_carry = {}
    expected_qfb, slice_qfb_owners = _slice_qfb_claims(module, routes)
    protected = set()
    q_feedback_names = set()

    for chain in chains:
        for before, after in zip(chain, chain[1:]):
            edge = _carry_edge(before.site, after.site)
            if edge in expected_carry:
                _reject("two logical links claim protected carry PIP %s -> %s" % edge)
            expected_carry[edge] = before.cout
            protected.add(edge)
            route = routes.get(before.cout)
            route_name = ", ".join(aliases.get(before.cout, ("bit %d" % before.cout,)))
            if route is None:
                _reject("internal carry net %s has no ROUTING attribute" % route_name)
            expected_root = edge[0]
            if route.edges != frozenset({edge}) or route.roots != frozenset({expected_root}):
                _reject("internal carry net %s does not contain its exact one-edge route" %
                        route_name)

        for item in chain[1:]:
            connections = item.cell.get("connections") or {}
            q_bits = _bits(connections.get("Q"))
            inputs = connections.get("I") or []
            own_indices = ([index for index, bit in enumerate(inputs)
                            if q_bits and bit == q_bits[0]] if len(q_bits) == 1 else [])
            if own_indices and own_indices != [1]:
                _reject("carry cell %r uses own Q outside the typed B/I[1] feedback" %
                        item.name)
            if not own_indices:
                continue
            if not item.ff_used:
                _reject("unregistered carry cell %r claims own-Q feedback" % item.name)
            q_bit = q_bits[0]
            q_root, bridge, qfb = _qfb_resources(item.site)
            q_feedback_names.add(item.name)
            route = routes.get(q_bit)
            route_name = ", ".join(aliases.get(q_bit, ("bit %d" % q_bit,)))
            if route is None:
                _reject("carry Q-feedback net %s has no ROUTING attribute" % route_name)
            # New short-chain placement must use the typed local path.  The
            # unchanged retained 25/33 and exact seam checkpoints may keep
            # their already admitted ordinary detours; if they do use the
            # typed edge, _slice_qfb_claims has already proven exact ownership.
            if profile == "short-same-tile":
                if item.name not in slice_qfb_owners:
                    _reject(
                        "carry Q-feedback net %s lacks its exact root/bridge/SLICE_QFB path" %
                        route_name
                    )
                protected.add(qfb)

    # Scan every serialized net, not only reconstructed owners.  A forged
    # ordinary net cannot hide a protected edge simply because all valid carry
    # chains are otherwise complete.
    claimed = {}
    for bit, route in routes.items():
        if route is None:
            continue
        for edge in route.edges:
            if (_protected_carry_wire(edge[0]) or
                    _protected_carry_wire(edge[1])):
                if expected_carry.get(edge) != bit:
                    _reject("bit %d makes foreign use of carry PIP %s -> %s" %
                            (bit, edge[0], edge[1]))
                if edge in claimed and claimed[edge] != bit:
                    _reject("protected carry PIP has multiple routed owners")
                claimed[edge] = bit
            if _qfb_edge(edge):
                if expected_qfb.get(edge) != bit:
                    _reject("bit %d makes foreign use of SLICE_QFB PIP %s -> %s" %
                            (bit, edge[0], edge[1]))
                if edge in claimed and claimed[edge] != bit:
                    _reject("protected SLICE_QFB PIP has multiple routed owners")
                claimed[edge] = bit
                protected.add(edge)
        for root in route.roots:
            if not _protected_carry_wire(root):
                continue
            owned_roots = {edge[0] for edge, owner in expected_carry.items()
                           if owner == bit}
            if root not in owned_roots:
                _reject("bit %d makes foreign root use of protected carry wire %s" %
                        (bit, root))

    result = []
    for chain in chains:
        chain_profile = profile if profile != "short-same-tile" else profile
        if len(chain) == 2:
            roles = ("SEED", "FIRST_TAIL")
        else:
            roles = tuple(
                "SEED" if index == 0 else
                "FIRST" if index == 1 else
                "TAIL" if index == len(chain) - 1 else
                "INTERIOR"
                for index in range(len(chain))
            )
        result.append(ValidatedCarryChain(
            tuple(item.name for item in chain),
            tuple(item.site for item in chain),
            roles,
            chain_profile,
            tuple(item.name for item in chain if item.ff_used),
            tuple(item.name for item in chain if item.name in q_feedback_names),
        ))
    result.sort(key=lambda chain: (chain.sites[0].x, chain.sites[0].y,
                                   chain.sites[0].z, len(chain.sites)))
    return CarryValidationResult(tuple(result), frozenset(protected))
