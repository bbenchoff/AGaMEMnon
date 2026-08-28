"""Independent intent and routed-netlist closure for the bounded N5.7A GCLK0."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agamemnon.engine import clock_resources


_SLICE_BEL = re.compile(r"X(\d+)Y(\d+)_SLICE(\d+)")
_SLICE_LEAF = re.compile(r"X\d+Y\d+_ClkMUX\d{2}")
_BRAM_TYPES = {"BRAM9K", "ALTA_BRAM9K", "ALTA_BRAM", "$mem", "BRAM"}
_BRAM_WIRES = frozenset({wire for edge in (
    (clock_resources.BRAM_ROOT_EDGE,) + tuple(clock_resources.BRAM_BRANCH_EDGES)
) for wire in edge})
_HEX64 = re.compile(r"[0-9a-f]{64}")


class ClockValidationError(ValueError):
    """Clock intent, ownership, or serialized route failed closed."""


@dataclass(frozen=True)
class _Route:
    edges: frozenset[tuple[str, str]]
    roots: frozenset[str]


@dataclass(frozen=True)
class ClockValidationResult:
    owner_bit: int | None
    source_profile: str | None
    source_class: str | None
    clocked_tiles: frozenset[tuple[int, int]]
    active_slice_leaves: frozenset[str]
    bram_edges: frozenset[tuple[str, str]]
    quarantined_extra_leaves: frozenset[str]
    quarantined_bitstream_sha256: str | None
    catalog_sha256: str
    topology_sha256: str


def _reject(reason):
    raise ClockValidationError("GCLK0 route: %s" % reason)


def _module(value):
    if not isinstance(value, dict):
        _reject("routed module/document is not an object")
    if "modules" not in value:
        return value
    modules = value.get("modules")
    if not isinstance(modules, dict) or not isinstance(modules.get("top"), dict):
        _reject("document requires exact modules['top']")
    marked = [name for name, module in modules.items()
              if str((module.get("attributes") or {}).get("top", "0"))
              in ("1", "00000000000000000000000000000001")]
    if len(marked) > 1 or (marked and marked != ["top"]):
        _reject("physical top marker conflicts with exact modules['top']")
    return modules["top"]


def _bits(value):
    if not isinstance(value, list):
        return ()
    return tuple(bit for bit in value
                 if isinstance(bit, int) and not isinstance(bit, bool))


def _scalar_bit(value, what):
    if (not isinstance(value, list) or len(value) != 1 or
            not isinstance(value[0], int) or isinstance(value[0], bool)):
        _reject("%s must be exactly one integer signal bit" % what)
    return value[0]


def _ff_used(cell, name):
    value = (cell.get("parameters") or {}).get("FF_USED")
    if isinstance(value, bool) or value is None:
        _reject("GENERIC_SLICE %r has missing/mistyped FF_USED" % name)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = int(value, 2) if all(char in "01" for char in value) else int(value, 10)
        except ValueError:
            _reject("GENERIC_SLICE %r has malformed FF_USED" % name)
    else:
        _reject("GENERIC_SLICE %r has missing/mistyped FF_USED" % name)
    if parsed not in (0, 1):
        _reject("GENERIC_SLICE %r FF_USED must be exactly zero or one" % name)
    return parsed


def _placed_bel(cell, name):
    attrs = cell.get("attributes") or {}
    values = [attrs[key] for key in ("BEL", "NEXTPNR_BEL") if key in attrs]
    if len(set(values)) > 1:
        _reject("cell %r has conflicting BEL/NEXTPNR_BEL placement" % name)
    if not values or not isinstance(values[0], str) or not values[0]:
        _reject("cell %r lacks a valid placed BEL" % name)
    return values[0]


def _parse_route(value, net_name):
    if value is None:
        return None
    if not isinstance(value, str):
        _reject("net %r has a non-string ROUTING attribute" % net_name)
    if not value.strip():
        return _Route(frozenset(), frozenset())
    fields = value.split(";")
    if len(fields) % 3:
        _reject("net %r ROUTING is not wire/PIP/strength triples" % net_name)
    edges, roots, triples = set(), set(), set()
    for wire, pip, strength in zip(fields[0::3], fields[1::3], fields[2::3]):
        if not wire or wire != wire.strip() or pip != pip.strip():
            _reject("net %r ROUTING contains an empty/non-canonical token" % net_name)
        if strength not in {"0", "1", "2", "3", "4", "5", "6"}:
            _reject("net %r ROUTING has invalid strength %r" % (net_name, strength))
        if (wire, pip) in triples:
            _reject("net %r ROUTING duplicates a wire/PIP triple" % net_name)
        triples.add((wire, pip))
        if not pip:
            if wire in roots:
                _reject("net %r ROUTING duplicates root %s" % (net_name, wire))
            roots.add(wire); continue
        if pip.count(".") != 1:
            _reject("net %r ROUTING has malformed PIP %r" % (net_name, pip))
        src, dst = pip.split(".")
        if dst != wire:
            _reject("net %r PIP destination %s does not match wire %s" %
                    (net_name, dst, wire))
        if (src, dst) in edges:
            _reject("net %r ROUTING duplicates PIP %s" % (net_name, pip))
        edges.add((src, dst))
    return _Route(frozenset(edges), frozenset(roots))


def _protected_wire(wire):
    return (wire == clock_resources.SPINE or _SLICE_LEAF.fullmatch(wire) is not None or
            wire in _BRAM_WIRES)


def _protected_route(route):
    return route is not None and (
        any(_protected_wire(src) or _protected_wire(dst)
            for src, dst in route.edges) or
        any(_protected_wire(root) for root in route.roots)
    )


def _routes_by_bit(module):
    routes, aliases = {}, {}
    netnames = module.get("netnames") or {}
    if not isinstance(netnames, dict):
        _reject("top module netnames is not a mapping")
    for name, net in netnames.items():
        if not isinstance(net, dict):
            _reject("netname %r is not an object" % name)
        attrs = net.get("attributes") or {}
        explicit = "ROUTING" in attrs
        route = _parse_route(attrs.get("ROUTING"), name) if explicit else None
        bits = net.get("bits")
        if _protected_route(route) and not (
                isinstance(bits, list) and len(bits) == 1 and
                isinstance(bits[0], int) and not isinstance(bits[0], bool)):
            _reject("net %r claims clock resources without one integer alias" % name)
        for bit in _bits(bits):
            aliases.setdefault(bit, []).append(name)
            if bit not in routes:
                routes[bit] = route
            elif explicit and routes[bit] is not None and routes[bit] != route:
                _reject("signal aliases for bit %d disagree about ROUTING (%s)" %
                        (bit, ", ".join(aliases[bit])))
            elif explicit:
                routes[bit] = route
    return routes


def _drivers(module):
    result = {}
    for name, cell in (module.get("cells") or {}).items():
        directions = cell.get("port_directions") or {}
        for port, value in (cell.get("connections") or {}).items():
            if directions.get(port) not in ("output", "inout"):
                continue
            for bit in _bits(value):
                result.setdefault(bit, []).append(("cell", name, port, cell))
    for name, port in (module.get("ports") or {}).items():
        if port.get("direction") not in ("input", "inout"):
            continue
        for bit in _bits(port.get("bits")):
            result.setdefault(bit, []).append(("port", name, port.get("direction"), port))
    return result


def _source_for_bit(module, bit, catalog, require_complete):
    drivers = _drivers(module).get(bit, [])
    matches = []
    for endpoint in drivers:
        if endpoint[0] != "cell":
            continue
        _kind, name, port, cell = endpoint
        attrs = cell.get("attributes") or {}
        bel_values = [attrs[key] for key in ("BEL", "NEXTPNR_BEL") if key in attrs]
        if len(set(bel_values)) > 1:
            _reject("clock source cell %r has conflicting placement" % name)
        bel = bel_values[0] if bel_values else None
        for profile in catalog.profiles:
            endpoint_matches = (cell.get("type"), port) == (
                profile.cell_type, profile.port
            )
            placement_matches = bel == profile.bel or (
                bel is None and not require_complete
            )
            if endpoint_matches and placement_matches:
                matches.append((endpoint, profile))
    if len(drivers) != 1 or len(matches) != 1:
        _reject("clock owner bit %d must have exactly one typed source driver" % bit)
    profile = matches[0][1]
    if not profile.admitted:
        _reject("source profile %s is classified but unsupported" % profile.profile)
    return profile


def _active_endpoints(module, require_complete):
    active, inactive, tiles, active_bits, bram_bits = {}, {}, set(), set(), set()
    for name, cell in (module.get("cells") or {}).items():
        if not isinstance(cell, dict):
            _reject("cell %r is not an object" % name)
        if cell.get("type") == "GENERIC_SLICE":
            ff_used = _ff_used(cell, name)
            connections = cell.get("connections") or {}
            if ff_used:
                bit = _scalar_bit(connections.get("CLK"), "active FF %r CLK" % name)
                active_bits.add(bit)
                attrs = cell.get("attributes") or {}
                surfaces = [attrs[key] for key in ("BEL", "NEXTPNR_BEL") if key in attrs]
                if len(set(surfaces)) > 1:
                    _reject("cell %r has conflicting BEL/NEXTPNR_BEL placement" % name)
                if not surfaces and not require_complete:
                    continue
                bel = _placed_bel(cell, name)
                match = _SLICE_BEL.fullmatch(bel)
                if match is None or not 0 <= int(match.group(3)) < 16:
                    _reject("active FF %r is not placed at a slice BEL" % name)
                leaf = "X%sY%s_ClkMUX%02d" % (
                    match.group(1), match.group(2), int(match.group(3)))
                if leaf in active:
                    _reject("active FFs duplicate slice clock leaf %s" % leaf)
                active[leaf] = bit
                tiles.add((int(match.group(1)), int(match.group(2))))
            else:
                clk = connections.get("CLK")
                if (isinstance(clk, list) and len(clk) == 1 and
                        isinstance(clk[0], int) and not isinstance(clk[0], bool)):
                    attrs = cell.get("attributes") or {}
                    bel = attrs.get("NEXTPNR_BEL", attrs.get("BEL"))
                    match = _SLICE_BEL.fullmatch(str(bel))
                    if match is not None:
                        inactive["X%sY%s_ClkMUX%02d" % (
                            match.group(1), match.group(2), int(match.group(3)))] = clk[0]
        if cell.get("type") in _BRAM_TYPES:
            connected = False
            for port in ("Clk0", "Clk1"):
                value = (cell.get("connections") or {}).get(port)
                if (isinstance(value, list) and len(value) == 1 and
                        isinstance(value[0], int) and not isinstance(value[0], bool)):
                    bram_bits.add(value[0])
                    connected = True
            if connected:
                if cell.get("type") != "ALTA_BRAM9K":
                    _reject("clocked BRAM %r must use exact ALTA_BRAM9K type" % name)
                attrs = cell.get("attributes") or {}
                surfaces = [attrs[key] for key in ("BEL", "NEXTPNR_BEL") if key in attrs]
                if len(set(surfaces)) > 1:
                    _reject("clocked BRAM %r has conflicting placement" % name)
                if surfaces and surfaces[0] != "X13Y4_BRAM":
                    _reject("clocked BRAM %r must be placed at X13Y4_BRAM" % name)
                if require_complete and not surfaces:
                    _reject("clocked BRAM %r lacks exact X13Y4_BRAM placement" % name)
    return active, inactive, frozenset(tiles), frozenset(active_bits), frozenset(bram_bits)


def _load_quarantine(chipdb_root, catalog):
    path = clock_resources.chipdb_path(clock_resources.LEGACY_QUARANTINE_NAME, chipdb_root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _reject("cannot read legacy quarantine: %s" % exc)
    if document.get("schema") != 1 or document.get("class") != "GCLK0_LEGACY_EXTRA_LEAVES":
        _reject("legacy quarantine has wrong schema/class")
    leaf_sets = document.get("leaf_sets")
    artifacts = document.get("artifacts")
    if not isinstance(leaf_sets, dict) or not isinstance(artifacts, list) or len(artifacts) != 19:
        _reject("legacy quarantine must contain exactly 19 artifacts")
    expanded, routed_hashes, module_hashes = [], set(), set()
    for name, leaves in leaf_sets.items():
        if (not isinstance(name, str) or not isinstance(leaves, list) or
                leaves != sorted(set(leaves)) or
                any(_SLICE_LEAF.fullmatch(str(leaf)) is None for leaf in leaves)):
            _reject("legacy quarantine leaf set %r is malformed" % name)
    for row in artifacts:
        required = {"routed_sha256", "canonical_module_sha256", "profile", "owner_bit",
                    "bitstream_sha256", "leaf_set"}
        if not isinstance(row, dict) or set(row) != required:
            _reject("legacy quarantine artifact has wrong fields")
        hashes = (row["routed_sha256"], row["canonical_module_sha256"],
                  row["bitstream_sha256"])
        if any(not isinstance(value, str) or _HEX64.fullmatch(value) is None
               for value in hashes):
            _reject("legacy quarantine artifact has malformed hash")
        if row["routed_sha256"] in routed_hashes or row["canonical_module_sha256"] in module_hashes:
            _reject("legacy quarantine artifact hashes are not unique")
        profile = catalog.by_id(row["profile"])
        if (profile is None or not profile.admitted or profile.profile not in {
                "MCU_BUS_DEFAULT_V1", "HSE_PLL_CLKIN_V1"}):
            _reject("legacy quarantine requires an exact admitted retained profile")
        if type(row["owner_bit"]) is not int or row["leaf_set"] not in leaf_sets:
            _reject("legacy quarantine owner/leaf-set identity is malformed")
        routed_hashes.add(row["routed_sha256"]); module_hashes.add(row["canonical_module_sha256"])
        expanded.append((row, frozenset(leaf_sets[row["leaf_set"]])))
    if sum(len(leaves) for _row, leaves in expanded) != 440:
        _reject("legacy quarantine must describe exactly 440 leaf occurrences")
    return tuple(expanded)


def _module_sha256(module):
    raw = json.dumps(module, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _option(options, name, default=None):
    if options is None:
        return default
    if hasattr(options, "integer"):
        try:
            return options.integer(name)
        except (KeyError, ValueError):
            pass
    if isinstance(options, dict):
        return options.get(name, default)
    return default


def _option_enabled(options, name):
    if options is not None and hasattr(options, "enabled"):
        try:
            return options.enabled(name)
        except (KeyError, ValueError):
            pass
    value = _option(options, name)
    return value not in (None, "", 0, "0", False, "false", "False", "no", "No")


def _validate(module_value, chipdb_root=None, options=None, routed_sha256=None,
              require_complete=True):
    module = _module(module_value)
    try:
        catalog = clock_resources.load_source_catalog(chipdb_root)
    except clock_resources.ClockResourceError as exc:
        _reject(str(exc))
    active, inactive, tiles, active_bits, bram_bits = _active_endpoints(
        module, require_complete
    )
    owners = set(active_bits) | set(bram_bits)
    routes = _routes_by_bit(module)
    protected_bits = {bit for bit, route in routes.items() if _protected_route(route)}
    if len(owners) > 1:
        _reject("active endpoints use more than one whole-device clock owner")
    if not owners:
        if protected_bits:
            _reject("clock resources are claimed without an active endpoint")
        return ClockValidationResult(
            None, None, None, frozenset(), frozenset(), frozenset(), frozenset(), None,
            catalog.digest, clock_resources.EXPECTED_TOPOLOGY_SHA256,
        )
    owner = next(iter(owners))
    if protected_bits - {owner}:
        _reject("foreign signal alias claims protected clock resources")
    profile = _source_for_bit(module, owner, catalog, require_complete)
    if _option(options, "AGAMEMNON_NGCLK", 1) not in (1, "1"):
        _reject("strict GCLK0 closure requires AGAMEMNON_NGCLK=1")
    if _option(options, "AGAMEMNON_CLK_SEAM", 5) not in (5, "5"):
        _reject("strict GCLK0 closure requires the qualified seam selector 5")
    for name in ("AGAMEMNON_NOSPINE", "AGAMEMNON_NO_SEAM", "AGAMEMNON_NO_CLKGEN"):
        if _option_enabled(options, name):
            _reject("strict GCLK0 closure does not admit %s" % name)
    if profile.rate_policy == "SUPPORTED_PLL_RATIOS" and options is not None:
        from agamemnon.engine import pll_emit
        try:
            pll_emit.require_supported_ratio(
                int(_option(options, "AGAMEMNON_SYSCLK")),
                int(_option(options, "AGAMEMNON_HSE")),
            )
        except (TypeError, ValueError) as exc:
            _reject("source profile %s has unsupported PLL options: %s" %
                    (profile.profile, exc))
    expected_leaves = frozenset(active)
    expected_bram = (frozenset({clock_resources.BRAM_ROOT_EDGE}) |
                     clock_resources.BRAM_BRANCH_EDGES) if bram_bits else frozenset()
    expected_edges = ({(clock_resources.SPINE, leaf) for leaf in expected_leaves} |
                      set(expected_bram))
    if profile.entry_edge is not None:
        expected_edges.add(profile.entry_edge)
    expected_roots = {profile.root_wire}
    route = routes.get(owner)
    actual_edges = set() if route is None else set(route.edges)
    actual_roots = set() if route is None else set(route.roots)
    actual_protected = {edge for edge in actual_edges
                        if _protected_wire(edge[0]) or _protected_wire(edge[1])}
    extra_edges = actual_protected - expected_edges
    extra_leaves = frozenset(dst for src, dst in extra_edges
                             if src == clock_resources.SPINE and
                             _SLICE_LEAF.fullmatch(dst) is not None)
    if extra_edges != {(clock_resources.SPINE, leaf) for leaf in extra_leaves}:
        _reject("route claims a foreign or wrong-class clock edge")
    quarantined = frozenset()
    quarantined_bitstream_sha256 = None
    if extra_leaves:
        if routed_sha256 is None or not isinstance(routed_sha256, str):
            _reject("inactive/extra slice clock leaves are not admitted")
        module_sha256 = _module_sha256(module)
        for row, leaves in _load_quarantine(chipdb_root, catalog):
            if (row["routed_sha256"] == routed_sha256 and
                    row["canonical_module_sha256"] == module_sha256 and
                    row["profile"] == profile.profile and row["owner_bit"] == owner and
                    leaves == extra_leaves):
                quarantined = leaves; break
        if not quarantined:
            _reject("inactive/extra slice clock leaves do not match an exact quarantine")
        if any(inactive.get(leaf) != owner for leaf in quarantined):
            _reject("quarantined leaf is not an inactive FF leaf on the admitted owner")
        quarantined_bitstream_sha256 = row["bitstream_sha256"]
    missing_edges = expected_edges - actual_protected
    if require_complete and (missing_edges or actual_roots != expected_roots):
        _reject("routed owner tree is incomplete or has the wrong source root")
    if not require_complete and (
            actual_protected - expected_edges - {(clock_resources.SPINE, leaf)
                                                  for leaf in quarantined} or
            not actual_roots <= expected_roots):
        _reject("partial routed owner tree contains a foreign edge/root")
    if bram_bits and bram_bits != {owner}:
        _reject("BRAM clocks do not share the one admitted owner")
    return ClockValidationResult(
        owner, profile.profile, profile.source_class, tiles, expected_leaves,
        expected_bram, quarantined, quarantined_bitstream_sha256, catalog.digest,
        clock_resources.EXPECTED_TOPOLOGY_SHA256,
    )


def validate_clock_intent(module, chipdb_root=None, options=None):
    """Validate typed source/endpoints and any fixed partial route before nextpnr."""
    return _validate(module, chipdb_root, options, require_complete=False)


def validate_routed_clock(module, chipdb_root=None, options=None, *,
                          routed_sha256=None, require_complete=True):
    """Reconstruct and strictly close the serialized GCLK0 owner tree."""
    return _validate(module, chipdb_root, options, routed_sha256, require_complete)
