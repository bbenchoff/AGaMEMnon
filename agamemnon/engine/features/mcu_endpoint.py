"""Fail-closed routed validation for the one typed HWDATA25 endpoint.

N5.8A deliberately admits one logical MCU-to-fabric lane.  The cell name has
no authority: intent is carried by four explicit attributes and is resolved
against one hash-pinned capability row.  This module independently rebuilds
the physical source, route tree, and every slice input sink before confidence
or bitstream emission.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


INTERFACE_ATTRIBUTE = "AGRV2K_MCU_ENDPOINT_INTERFACE"
LANE_ATTRIBUTE = "AGRV2K_MCU_ENDPOINT_LANE"
MODE_ATTRIBUTE = "AGRV2K_MCU_ENDPOINT_MODE"
VERSION_ATTRIBUTE = "AGRV2K_MCU_ENDPOINT_VERSION"
INTENT_ATTRIBUTES = (
    INTERFACE_ATTRIBUTE,
    LANE_ATTRIBUTE,
    MODE_ATTRIBUTE,
    VERSION_ATTRIBUTE,
)

_CAPABILITY_HEADER = (
    "schema_version", "interface", "lane", "cell_type", "cell_port",
    "hard_pin", "hard_bel", "source_root", "first_hop_dst", "mode",
    "selector_owner", "selector_field", "selector_selection",
    "evidence_tier", "evidence",
)
_SLICE_BEL = re.compile(r"X(\d+)Y(\d+)_SLICE(\d+)")


@dataclass(frozen=True)
class McuEndpointCapability:
    schema_version: int
    interface: str
    lane: int
    cell_type: str
    cell_port: str
    hard_pin: str
    hard_bel: str
    source_root: str
    first_hop_dst: str
    mode: str
    selector_owner: str
    selector_field: str
    selector_selection: int
    evidence_tier: str
    evidence: str

    @property
    def first_hop(self):
        return self.source_root, self.first_hop_dst


@dataclass(frozen=True)
class McuEndpointSink:
    cell: str
    port: str
    bit_index: int
    bel: str
    wire: str


@dataclass(frozen=True)
class McuEndpointRequirement:
    endpoint_cell: str
    signal_bit: int
    capability: McuEndpointCapability
    sinks: tuple[McuEndpointSink, ...]
    route_carrier: str | None

    @property
    def active(self):
        return bool(self.sinks)


def _reject(reason):
    raise SystemExit("MCU endpoint: %s" % reason)


def _one_csv(path, header, label):
    try:
        with Path(path).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != tuple(header):
                _reject("%s has a malformed schema" % label)
            rows = list(reader)
    except OSError as exc:
        _reject("cannot read %s: %s" % (label, exc))
    if len(rows) != 1:
        _reject("%s must contain exactly one capability row" % label)
    return rows[0]


def _integer(value, field, label):
    try:
        if value is None or str(value).strip() != str(int(str(value), 10)):
            raise ValueError
        return int(str(value), 10)
    except (TypeError, ValueError):
        _reject("%s field %s is not a canonical decimal integer" % (label, field))


def load_mcu_endpoint_capability(chipdb_root):
    """Load and cross-check the exact one-row HWDATA25 authority."""

    root = Path(chipdb_root)
    table = root / "mcu_endpoint_capabilities.csv"
    manifest_path = root / "mcu_endpoint_capability_manifest.json"
    try:
        raw = table.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        _reject("capability table or manifest is unreadable: %s" % exc)
    expected_manifest = {
        "schema_version": 1,
        "scope": "HWDATA25-only",
        "table": table.name,
        "table_bytes": len(raw),
        "table_rows": 1,
        "table_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if manifest != expected_manifest:
        _reject("capability manifest does not bind the exact table bytes")

    row = _one_csv(table, _CAPABILITY_HEADER, table.name)
    capability = McuEndpointCapability(
        schema_version=_integer(row["schema_version"], "schema_version", table.name),
        interface=row["interface"],
        lane=_integer(row["lane"], "lane", table.name),
        cell_type=row["cell_type"],
        cell_port=row["cell_port"],
        hard_pin=row["hard_pin"],
        hard_bel=row["hard_bel"],
        source_root=row["source_root"],
        first_hop_dst=row["first_hop_dst"],
        mode=row["mode"],
        selector_owner=row["selector_owner"],
        selector_field=row["selector_field"],
        selector_selection=_integer(
            row["selector_selection"], "selector_selection", table.name,
        ),
        evidence_tier=row["evidence_tier"],
        evidence=row["evidence"],
    )
    if capability != McuEndpointCapability(
        1, "HWDATA", 25, "MCU_DIN", "DIN", "MCU_DIN69",
        "X10Y5_MCU_DIN69", "X13Y9_BufMUX07", "X13Y9_InputMUX06",
        "DIRECT_FABRIC_INPUT", "mcu", "InputMUX6", 0,
        "silicon_lane_identity",
        "group6-hwdata25-lane-identity-and-vendor-ahbrwide32-route",
    ):
        _reject("the sole capability row is not the bounded HWDATA25 authority")

    lane_path = root / "mcu_hwdata_lanes.csv"
    try:
        with lane_path.open(encoding="utf-8", newline="") as stream:
            lanes = list(csv.DictReader(stream))
    except OSError as exc:
        _reject("cannot validate against mcu_hwdata_lanes.csv: %s" % exc)
    matches = [row for row in lanes if row.get("logical_bit") == "25"]
    expected_lane = {
        "logical_bit": "25", "bel_bit": "69", "entry_x": "13",
        "entry_y": "9", "entry_res": "BufMUX07",
        "next_res": "InputMUX06", "evidence": "vendor-ahbrwide32",
    }
    if matches != [expected_lane]:
        _reject("capability conflicts with the unique HWDATA25 lane mapping")

    corridor_path = root / "mcu_ahb32_corridors.csv"
    try:
        with corridor_path.open(encoding="utf-8", newline="") as stream:
            corridors = list(csv.DictReader(stream))
    except OSError as exc:
        _reject("cannot validate against mcu_ahb32_corridors.csv: %s" % exc)
    step_zero = [
        row for row in corridors
        if row.get("logical_bit") == "25" and row.get("step") == "0"
    ]
    if len(step_zero) != 1 or (
        step_zero[0].get("src_wire"), step_zero[0].get("dst_wire")
    ) != capability.first_hop:
        _reject("capability first hop conflicts with the HWDATA25 corridor")

    selector_path = root / "mcu_ahb32_pip_cfg.csv"
    try:
        with selector_path.open(encoding="utf-8", newline="") as stream:
            selector_rows = list(csv.DictReader(stream))
    except OSError as exc:
        _reject("cannot validate against mcu_ahb32_pip_cfg.csv: %s" % exc)
    selector = [
        row for row in selector_rows
        if (row.get("src_wire"), row.get("dst_wire")) == capability.first_hop
    ]
    if len(selector) != 1 or any((
        selector[0].get("cell_table") != capability.selector_owner,
        selector[0].get("cfg_group") != capability.selector_field,
        selector[0].get("clear_selectors") != "0",
        selector[0].get("set_selectors") != str(capability.selector_selection),
    )):
        _reject("capability first-hop selector identity is missing or contradictory")
    return capability


def _attribute_integer(cell_name, attributes, name):
    value = attributes.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value:
        _reject("cell %r attribute %s is not an integer" % (cell_name, name))
    try:
        if re.fullmatch(r"[01]+", value):
            return int(value, 2)
        return int(value, 0)
    except ValueError:
        _reject("cell %r attribute %s is not an integer" % (cell_name, name))


def _bits(cell_name, cell, port):
    connections = cell.get("connections")
    if not isinstance(connections, dict):
        _reject("cell %r has malformed connections" % cell_name)
    value = connections.get(port)
    if not isinstance(value, list) or any(
        not isinstance(bit, int) or isinstance(bit, bool) for bit in value
    ):
        _reject("connected port %s.%s is not an integer-bit list" % (cell_name, port))
    return tuple(value)


def _known_direction(cell_type, port):
    if cell_type == "MCU_DIN":
        return "output" if port == "DIN" else False
    if cell_type == "GENERIC_SLICE":
        if port in {"F", "Q", "COUT"}:
            return "output"
        if port in {"A", "B", "C", "D", "CLK", "I", "CIN"}:
            return "input"
        if re.fullmatch(r"I\[[0-3]\]", port):
            return "input"
        return False
    return None


def _direction(cell_name, cell, port):
    directions = cell.get("port_directions")
    if not isinstance(directions, dict) or port not in directions:
        _reject("connected port direction metadata is missing at %s.%s" %
                (cell_name, port))
    direction = directions[port]
    if direction not in {"input", "output", "inout"}:
        _reject("connected port direction metadata is unknown at %s.%s" %
                (cell_name, port))
    known = _known_direction(cell.get("type"), port)
    if known is False:
        _reject("connected port names an unknown %s port at %s.%s" %
                (cell.get("type"), cell_name, port))
    if known is not None and direction != known:
        _reject("connected port direction contradicts known %s semantics at %s.%s" %
                (cell.get("type"), cell_name, port))
    return direction


def _parse_route(name, value):
    if not isinstance(value, str) or not value:
        _reject("active signal route %r has no textual ROUTING attribute" % name)
    parts = value.split(";")
    if len(parts) % 3:
        _reject("route %r is not canonical wire/PIP/strength triples" % name)
    roots, edges, triples, wires = set(), set(), set(), set()
    for wire, pip, strength in zip(parts[0::3], parts[1::3], parts[2::3]):
        if not wire or strength not in {"0", "1", "2", "3", "4", "5", "6"}:
            _reject("route %r contains a malformed wire or strength" % name)
        if (wire, pip) in triples:
            _reject("route %r duplicates a wire/PIP triple" % name)
        triples.add((wire, pip))
        wires.add(wire)
        if not pip:
            if wire in roots:
                _reject("route %r duplicates a root" % name)
            roots.add(wire)
            continue
        if pip.count(".") != 1:
            _reject("route %r contains malformed PIP %r" % (name, pip))
        src, dst = pip.split(".")
        if dst != wire:
            _reject("route %r PIP destination disagrees with its wire" % name)
        if (src, dst) in edges:
            _reject("route %r duplicates PIP %s" % (name, pip))
        edges.add((src, dst))
        wires.add(src)
    return roots, edges, wires


def _route_for_bit(module, signal_bit):
    carriers = []
    all_routes = []
    netnames = module.get("netnames")
    if not isinstance(netnames, dict):
        _reject("physical module netnames is not an object")
    for name, net in netnames.items():
        if not isinstance(net, dict):
            _reject("netname %r is not an object" % name)
        attrs = net.get("attributes") or {}
        if not isinstance(attrs, dict):
            _reject("netname %r attributes is not an object" % name)
        bits = net.get("bits")
        if not isinstance(bits, list) or any(
            not isinstance(bit, int) or isinstance(bit, bool) for bit in bits
        ):
            if "ROUTING" in attrs:
                _reject("ROUTING carrier %r lacks exact integer bits" % name)
            continue
        if "ROUTING" in attrs:
            route = _parse_route(name, attrs["ROUTING"])
            all_routes.append((name, tuple(bits), route))
            if signal_bit in bits:
                if tuple(bits) != (signal_bit,):
                    _reject("typed endpoint route %r is not a scalar signal carrier" % name)
                carriers.append((name, attrs["ROUTING"], route))
    if not carriers:
        _reject("active typed endpoint signal has no ROUTING carrier")
    if len({raw for _name, raw, _route in carriers}) != 1:
        _reject("typed endpoint signal aliases disagree about ROUTING")
    return carriers[0][0], carriers[0][2], tuple(all_routes)


def _sink_wire(cell_name, cell, port, bit_index):
    bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL")
    match = _SLICE_BEL.fullmatch(str(bel))
    if not match:
        _reject("consumer %r has malformed or unbound slice NEXTPNR_BEL %r" %
                (cell_name, bel))
    x, y, z = (int(match.group(index)) for index in (1, 2, 3))
    if port == "I":
        pin = bit_index
    else:
        pin_match = re.fullmatch(r"I\[([0-3])\]", port)
        if not pin_match or bit_index != 0:
            _reject("consumer %r uses incompatible endpoint port %s" %
                    (cell_name, port))
        pin = int(pin_match.group(1))
    if pin not in range(4):
        _reject("consumer %r uses out-of-range LUT input %d" % (cell_name, pin))
    return bel, "X%dY%d_IMUX%02d" % (x, y, 4 * z + pin)


def validate_module_mcu_endpoints(module, chipdb_root):
    """Validate every explicit endpoint intent and return it by endpoint cell."""

    if not isinstance(module, dict) or not isinstance(module.get("cells"), dict):
        _reject("physical module cells is not an object")
    cells = module["cells"]
    if not any(
        any(name in (cell.get("attributes") or {}) for name in INTENT_ATTRIBUTES)
        for cell in cells.values() if isinstance(cell, dict)
    ):
        return {}  # retained attribute-absent routed artifacts need no new table
    capability = load_mcu_endpoint_capability(chipdb_root)
    typed = []
    for cell_name, cell in cells.items():
        if not isinstance(cell, dict):
            _reject("cell %r is not an object" % cell_name)
        attrs = cell.get("attributes")
        if attrs is None:
            attrs = {}
        if not isinstance(attrs, dict):
            _reject("cell %r attributes is not an object" % cell_name)
        present = [name for name in INTENT_ATTRIBUTES if name in attrs]
        if not present:
            continue
        if len(present) != len(INTENT_ATTRIBUTES):
            _reject("cell %r has partial endpoint intent metadata" % cell_name)
        interface = attrs[INTERFACE_ATTRIBUTE]
        mode = attrs[MODE_ATTRIBUTE]
        if not isinstance(interface, str) or not isinstance(mode, str):
            _reject("cell %r endpoint interface/mode metadata is malformed" % cell_name)
        lane = _attribute_integer(cell_name, attrs, LANE_ATTRIBUTE)
        version = _attribute_integer(cell_name, attrs, VERSION_ATTRIBUTE)
        if (interface, lane, mode, version) != (
            capability.interface, capability.lane,
            capability.mode, capability.schema_version,
        ):
            _reject(
                "cell %r endpoint intent has no exact capability "
                "(HWDATA24/26 and other lanes are not generalized)" % cell_name
            )
        if cell.get("type") != capability.cell_type:
            _reject("cell %r endpoint intent requires type %s" %
                    (cell_name, capability.cell_type))
        _direction(cell_name, cell, capability.cell_port)
        bits = _bits(cell_name, cell, capability.cell_port)
        if len(bits) != 1:
            _reject("cell %r endpoint port must carry exactly one signal bit" % cell_name)
        typed.append((cell_name, cell, bits[0]))
    if len(typed) > 1:
        _reject("duplicate HWDATA25 endpoint intents are forbidden")
    if not typed:
        return {}

    endpoint_name, endpoint, signal_bit = typed[0]
    endpoint_bel = (endpoint.get("attributes") or {}).get("NEXTPNR_BEL")
    if endpoint_bel != capability.hard_bel:
        _reject("endpoint %r is bound to %r, not exact hard BEL %s" %
                (endpoint_name, endpoint_bel, capability.hard_bel))

    sinks = []
    for cell_name, cell in cells.items():
        connections = cell.get("connections")
        if not isinstance(connections, dict):
            _reject("cell %r has malformed connections" % cell_name)
        for port, raw_bits in connections.items():
            if not isinstance(raw_bits, list):
                _reject("connected port %s.%s is malformed" % (cell_name, port))
            indices = [index for index, bit in enumerate(raw_bits)
                       if bit == signal_bit and isinstance(bit, int)
                       and not isinstance(bit, bool)]
            if not indices:
                continue
            direction = _direction(cell_name, cell, port)
            if cell_name == endpoint_name and port == capability.cell_port:
                if indices != [0] or direction != "output":
                    _reject("typed endpoint source port is contradictory")
                continue
            if direction != "input":
                _reject("typed endpoint signal has a foreign or duplicate driver at %s.%s" %
                        (cell_name, port))
            if cell.get("type") != "GENERIC_SLICE":
                _reject("typed endpoint drives non-slice consumer %s.%s" %
                        (cell_name, port))
            if len(indices) != 1:
                _reject("typed endpoint appears more than once on consumer %s.%s" %
                        (cell_name, port))
            bel, wire = _sink_wire(cell_name, cell, port, indices[0])
            sinks.append(McuEndpointSink(cell_name, port, indices[0], bel, wire))

    sinks.sort(key=lambda item: (item.cell, item.port, item.bit_index))
    if not sinks:
        # The kept public boundary cell may exist while the logical lane is
        # unused.  No native placement or route authority is activated then.
        return {endpoint_name: McuEndpointRequirement(
            endpoint_name, signal_bit, capability, (), None,
        )}

    route_name, route, all_routes = _route_for_bit(module, signal_bit)
    roots, edges, wires = route
    if roots != {capability.source_root}:
        _reject("typed endpoint route must have exactly the capability source root")
    if capability.first_hop not in edges:
        _reject("typed endpoint route omits its mandatory first hop")
    if {edge for edge in edges if edge[0] == capability.source_root} != {
        capability.first_hop
    }:
        _reject("typed endpoint source root uses a wrong or additional first hop")

    reachable = set(roots)
    pending = set(edges)
    while pending:
        admitted = {edge for edge in pending if edge[0] in reachable}
        if not admitted:
            _reject("typed endpoint ROUTING contains a disconnected tree")
        for edge in admitted:
            reachable.add(edge[1])
        pending -= admitted
    for sink in sinks:
        if sink.wire not in reachable or sink.wire not in wires:
            _reject("typed endpoint route does not reach consumer %s.%s at %s" %
                    (sink.cell, sink.port, sink.wire))

    typed_resources = set(wires)
    for other_name, other_bits, (other_roots, other_edges, other_wires) in all_routes:
        if signal_bit in other_bits:
            continue
        collision = typed_resources.intersection(other_wires)
        if collision or capability.first_hop in other_edges:
            _reject("foreign route %r collides with typed endpoint resource %s" %
                    (other_name, sorted(collision)[0] if collision else
                     "%s.%s" % capability.first_hop))

    return {endpoint_name: McuEndpointRequirement(
        endpoint_name, signal_bit, capability, tuple(sinks), route_name,
    )}


def validate_document_mcu_endpoints(document, chipdb_root):
    modules = document.get("modules") if isinstance(document, dict) else None
    if not isinstance(modules, dict) or not isinstance(modules.get("top"), dict):
        _reject("routed document requires exact modules['top']")
    return validate_module_mcu_endpoints(modules["top"], chipdb_root)
