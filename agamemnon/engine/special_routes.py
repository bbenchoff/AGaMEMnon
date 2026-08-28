"""Typed, digest-bound special-route authorities shared by arch, CLI, and bitgen.

N5.5 deliberately contains one small pilot class.  The class is not a routing
selector claim and it does not add graph resources: it describes ownership and
closure rules for 36 already-qualified L48 left-output PIPs.  Keeping the
catalog and its verifier here prevents the C++ uarch, cached graph, direct pack
path, and final emitter from silently disagreeing about that boundary.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path


CLASS = "L48_LEFT_OUTPUT"
SCHEMA = "1"
VERSION = "1"
ROUTED_VERSION = "v1"
DEVICE = "AGRV2KL48"
PACKAGE = "L48"
PROFILE = "physical-io"
CATALOG_NAME = "special_routes_l48_left_output.csv"
DEV_CATALOG_NAME = "dev_special_routes.csv"
DEV_META_NAME = "dev_special_route_meta.csv"
TOKEN_CLASS = "AGAMEMNON_SPECIAL_ROUTE_CLASS"
TOKEN_LANE = "AGAMEMNON_SPECIAL_ROUTE_LANE"
TOKEN_DIGEST = "AGAMEMNON_SPECIAL_ROUTE_CATALOG_SHA256"
TOKEN_VERSION = "AGAMEMNON_SPECIAL_ROUTE_VERSION"
MODULE_SCHEMA = "AGAMEMNON_SPECIAL_ROUTE_SCHEMA"
MODULE_DEVICE = "AGAMEMNON_SPECIAL_ROUTE_DEVICE"
MODULE_PACKAGE = "AGAMEMNON_SPECIAL_ROUTE_PACKAGE"
MODULE_PROFILE = "AGAMEMNON_SPECIAL_ROUTE_PROFILE"
MODULE_ENABLED = "AGAMEMNON_SPECIAL_ROUTE_ENABLED"
DEVDB_ENV = "AGAMEMNON_SPECIAL_ROUTE_DEVDB"
EXPECTED_CATALOG_SHA256 = (
    "c900368abe07fe61e0c97a76dcb11e9e8b3d9acdfc56ada99d56de6e5bf30e8e"
)
EXPECTED_PHYSICAL_GRAPH_PIP_COUNT = 248306
EXPECTED_PHYSICAL_GRAPH_SHA256 = (
    "c3608bf460a453467fb76dda803cb0c3d1e0caf4c7ee07ded60142fe792dcb97"
)
# Marker migration is intentionally hash-only.  These four immutable routed
# inputs are already pinned in qualification/pack_regression.json; the two
# RV32I rows are also bound by qualification/serv_compliance_evidence.jsonl,
# and the four-lane row is bound by left_edge_output_evidence.jsonl.  No path,
# filename, or merely topologically similar copy receives this exception.
LEGACY_RETAINED_SHA256 = (
    "b2ac1448106262a71bba927f03e262808adf620c49aa310a06f12f1ee76f3d3c"
)
AUTHENTICATED_RETAINED_SHA256S = frozenset({
    LEGACY_RETAINED_SHA256,
    "2fbb058fdfc8a054917aba6e9d0b3bae5a9164b3bbfe962c4c05b7042493d805",
    "e3cec1567e1dbcd6aafb9b734407c13b8c3e469fced23ac84eb62286eecaf576",
    "4ffe1076ce65a9a2e0bbbdcbeb67900c6c6249367b3c4f7da41210fdec4563d2",
})

FROZEN_LANES = (
    ("PIN_25", "X14Y11_SLICE4", "Q", "X0Y4_IOB0", "I"),
    ("PIN_26", "X14Y11_SLICE5", "Q", "X0Y4_IOB1", "I"),
    ("PIN_27", "X14Y11_SLICE6", "Q", "X0Y4_IOB2", "I"),
    ("PIN_28", "X14Y11_SLICE7", "Q", "X0Y4_IOB3", "I"),
)

FIELDS = (
    "schema", "device", "package", "profile", "class", "version", "lane",
    "pin", "source_bel", "source_port", "sink_bel", "sink_port", "step",
    "src_wire", "dst_wire", "evidence",
)


class SpecialRouteError(ValueError):
    """A typed special-route input failed closed."""


@dataclass(frozen=True)
class Edge:
    lane: int
    step: int
    src: str
    dst: str


@dataclass(frozen=True)
class Lane:
    index: int
    pin: str
    source_bel: str
    source_port: str
    sink_bel: str
    sink_port: str
    edges: tuple[Edge, ...]

    @property
    def wires(self):
        return frozenset(
            [edge.src for edge in self.edges] + [edge.dst for edge in self.edges]
        )


@dataclass(frozen=True)
class Catalog:
    rows: tuple[dict[str, str], ...]
    lanes: tuple[Lane, ...]
    digest: str

    @property
    def edges(self):
        return frozenset((edge.src, edge.dst) for lane in self.lanes for edge in lane.edges)

    @property
    def wires(self):
        return frozenset(wire for lane in self.lanes for wire in lane.wires)


@dataclass(frozen=True)
class ValidatedRoutedJson:
    """One byte-exact routed checkpoint and its validated parsed form."""

    raw: bytes
    document: dict
    result: dict
    sha256: str


def _canonical_bytes(rows):
    # The digest is independent of platform newlines and CSV quoting choices.
    lines = [",".join(FIELDS)]
    lines.extend(",".join(row[field] for field in FIELDS) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _parse_exact_csv(raw, path, fields):
    try:
        stream = io.StringIO(raw.decode("utf-8"), newline="")
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(fields):
            raise SpecialRouteError(
                "%s has wrong columns (expected %s)" %
                (path, ",".join(fields))
            )
        rows = []
        expected = set(fields)
        for row_index, row in enumerate(reader, 1):
            if set(row) != expected or any(row[field] is None for field in fields):
                raise SpecialRouteError(
                    "%s row %d does not have exactly %d fields" %
                    (path, row_index, len(fields))
                )
            rows.append(dict(row))
        return tuple(rows)
    except UnicodeDecodeError as exc:
        raise SpecialRouteError("cannot decode %s as UTF-8: %s" % (path, exc))


def _read_exact_csv(path, fields):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SpecialRouteError("cannot read %s: %s" % (path, exc))
    return _parse_exact_csv(raw, path, fields)


def catalog_path(chipdb_root=None):
    if chipdb_root is None:
        chipdb_root = Path(__file__).resolve().parents[1] / "chipdb"
    return Path(chipdb_root) / CATALOG_NAME


def load_catalog(chipdb_root=None):
    path = catalog_path(chipdb_root)
    rows = _read_exact_csv(path, FIELDS)

    if len(rows) != 36:
        raise SpecialRouteError("%s must contain exactly 36 PIPs, found %d" % (CLASS, len(rows)))
    lanes = []
    all_wires = set()
    all_edges = set()
    for lane_index, edge_count in enumerate((10, 9, 9, 8)):
        selected = [row for row in rows if row["lane"] == str(lane_index)]
        selected.sort(key=lambda row: int(row["step"]))
        if len(selected) != edge_count:
            raise SpecialRouteError(
                "%s lane %d must contain %d PIPs, found %d" %
                (CLASS, lane_index, edge_count, len(selected))
            )
        expected_constants = {
            "schema": SCHEMA, "device": DEVICE, "package": PACKAGE,
            "profile": PROFILE, "class": CLASS, "version": VERSION,
            "source_port": "Q", "sink_port": "I",
        }
        for step, row in enumerate(selected):
            for key, value in expected_constants.items():
                if row[key] != value:
                    raise SpecialRouteError(
                        "%s lane %d step %d has %s=%r, expected %r" %
                        (CLASS, lane_index, step, key, row[key], value)
                    )
            if row["step"] != str(step):
                raise SpecialRouteError("%s lane %d steps are not contiguous" % (CLASS, lane_index))
            if step and selected[step - 1]["dst_wire"] != row["src_wire"]:
                raise SpecialRouteError("%s lane %d is not continuous at step %d" %
                                        (CLASS, lane_index, step))
        identity_keys = ("pin", "source_bel", "source_port", "sink_bel", "sink_port")
        if any(tuple(row[key] for key in identity_keys) !=
               tuple(selected[0][key] for key in identity_keys) for row in selected):
            raise SpecialRouteError("%s lane %d changes endpoint identity" % (CLASS, lane_index))
        identity = tuple(selected[0][key] for key in identity_keys)
        if identity != FROZEN_LANES[lane_index]:
            raise SpecialRouteError(
                "%s lane %d endpoint identity is not the frozen qualified identity" %
                (CLASS, lane_index)
            )
        edges = tuple(Edge(lane_index, i, row["src_wire"], row["dst_wire"])
                      for i, row in enumerate(selected))
        lane = Lane(
            lane_index, selected[0]["pin"], selected[0]["source_bel"],
            selected[0]["source_port"], selected[0]["sink_bel"],
            selected[0]["sink_port"], edges,
        )
        if all_wires.intersection(lane.wires):
            raise SpecialRouteError("%s lanes are not wire-disjoint" % CLASS)
        all_wires.update(lane.wires)
        for edge in edges:
            if (edge.src, edge.dst) in all_edges:
                raise SpecialRouteError("%s contains a duplicate PIP" % CLASS)
            all_edges.add((edge.src, edge.dst))
        lanes.append(lane)
    if len(all_wires) != 40:
        raise SpecialRouteError("%s must protect exactly 40 wires, found %d" %
                                (CLASS, len(all_wires)))
    if any(row["lane"] not in {"0", "1", "2", "3"} for row in rows):
        raise SpecialRouteError("%s contains an unknown lane" % CLASS)
    digest = hashlib.sha256(_canonical_bytes(rows)).hexdigest()
    if digest != EXPECTED_CATALOG_SHA256:
        raise SpecialRouteError(
            "%s catalog digest is not the exact reviewed topology/evidence authority" % CLASS
        )
    return Catalog(rows, tuple(lanes), digest)


def _truthy(value):
    return value not in (None, "", "0", "false", "False", "no", "No")


def expected_enabled(environ=None):
    environ = os.environ if environ is None else environ
    return (environ.get("AGAMEMNON_DEVICE", DEVICE) == DEVICE and
            _truthy(environ.get("AGAMEMNON_PHYSICAL_IO")) and
            _truthy(environ.get("AGAMEMNON_LEFT_PAD_OUT")))


def emit_devdb_metadata(out_dir, chipdb_root=None, environ=None, graph_pips=()):
    """Emit the complete catalog plus profile/digest metadata into one devdb."""
    catalog = load_catalog(chipdb_root)
    out_dir = Path(out_dir)
    enabled = expected_enabled(environ)
    graph_pips = set(graph_pips)
    pips_by_name, graph_pip_count, graph_pips_sha256 = _devdb_pips(out_dir)
    if set(pips_by_name.values()) != graph_pips:
        raise SpecialRouteError(
            "emitted uarch graph does not match the graph supplied for metadata"
        )
    if enabled:
        missing = sorted(catalog.edges - graph_pips)
        if missing:
            raise SpecialRouteError(
                "%s physical-I/O graph lacks catalog PIP %s -> %s" %
                (CLASS, missing[0][0], missing[0][1])
            )
    with (out_dir / DEV_CATALOG_NAME).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(catalog.rows)
    metadata = (
        ("schema", SCHEMA), ("class", CLASS), ("version", VERSION),
        ("device", DEVICE), ("package", PACKAGE), ("profile", PROFILE),
        ("enabled", "1" if enabled else "0"),
        ("pip_count", str(len(catalog.edges))),
        ("wire_count", str(len(catalog.wires))),
        ("catalog_sha256", catalog.digest),
        ("graph_pip_count", str(graph_pip_count)),
        ("graph_pips_sha256", graph_pips_sha256),
    )
    with (out_dir / DEV_META_NAME).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("key", "value"))
        writer.writerows(metadata)
    return dict(metadata)


def _csv_dict(path, key="key", value="value"):
    result = {}
    for row in _read_exact_csv(path, (key, value)):
        if not row[key] or row[key] in result:
            raise SpecialRouteError("%s has duplicate/empty %s" % (path, key))
        result[row[key]] = row[value]
    return result


def _parse_env_summary(text):
    """Parse the exact semicolon-separated device-cache environment record."""
    if not text:
        return {}
    parsed = {}
    for token in text.split(";"):
        key, separator, value = token.partition("=")
        if not separator or not key or key in parsed:
            raise SpecialRouteError("uarch agamemnon_env summary is malformed")
        parsed[key] = value
    return parsed


def _devdb_pips(devdb):
    """Load one byte-exact generated PIP graph and return its identity."""
    path = Path(devdb) / "dev_pips.csv"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SpecialRouteError("cannot read %s: %s" % (path, exc))
    rows = _parse_exact_csv(
        raw, path,
        ("name", "type", "src", "dst", "delay_ns", "x", "y", "z"),
    )
    pips = {}
    for row in rows:
        name = row.get("name")
        endpoints = (row.get("src"), row.get("dst"))
        if not name or not all(endpoints) or name in pips:
            raise SpecialRouteError(
                "uarch special-route graph has duplicate/empty PIP identity"
            )
        if name != endpoints[0] + "." + endpoints[1]:
            raise SpecialRouteError(
                "uarch special-route named PIP endpoint drift at %s" % name
            )
        pips[name] = endpoints
    return pips, len(rows), hashlib.sha256(raw).hexdigest()


def _validated_devdb(devdb, chipdb_root=None):
    """Return one validated enabled flag and the exact graph snapshot checked."""
    devdb = Path(devdb)
    catalog = load_catalog(chipdb_root)
    for name in (DEV_CATALOG_NAME, DEV_META_NAME):
        if not (devdb / name).is_file():
            raise SpecialRouteError("uarch device database is missing %s" % name)
    metadata = _csv_dict(devdb / DEV_META_NAME)
    expected = {
        "schema": SCHEMA, "class": CLASS, "version": VERSION,
        "device": DEVICE, "package": PACKAGE, "profile": PROFILE,
        "pip_count": "36", "wire_count": "40", "catalog_sha256": catalog.digest,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise SpecialRouteError(
                "uarch special-route %s drift: got %r expected %r" %
                (key, metadata.get(key), value)
            )
    if metadata.get("enabled") not in ("0", "1"):
        raise SpecialRouteError("uarch special-route enabled flag is invalid")
    rows = _read_exact_csv(devdb / DEV_CATALOG_NAME, FIELDS)
    if hashlib.sha256(_canonical_bytes(rows)).hexdigest() != catalog.digest:
        raise SpecialRouteError("uarch special-route catalog/cache digest drift")
    dev_meta = _csv_dict(devdb / "dev_meta.csv")
    expected_dev_meta = {
        "special_route_class": CLASS,
        "special_route_enabled": metadata["enabled"],
        "special_route_catalog_sha256": catalog.digest,
    }
    for key, value in expected_dev_meta.items():
        if dev_meta.get(key) != value:
            raise SpecialRouteError(
                "uarch dev_meta special-route binding drift at %s: got %r expected %r" %
                (key, dev_meta.get(key), value)
            )
    env = _parse_env_summary(dev_meta.get("agamemnon_env", ""))
    physical = (env.get("AGAMEMNON_PHYSICAL_IO") == "1" and
                env.get("AGAMEMNON_LEFT_PAD_OUT") == "1")
    if (metadata["enabled"] == "1") != physical:
        raise SpecialRouteError("uarch special-route profile/cache mismatch")
    pips_by_name = None
    if metadata["enabled"] == "1":
        pips_by_name, graph_pip_count, graph_pips_sha256 = _devdb_pips(devdb)
        expected_graph = {
            "graph_pip_count": str(EXPECTED_PHYSICAL_GRAPH_PIP_COUNT),
            "graph_pips_sha256": EXPECTED_PHYSICAL_GRAPH_SHA256,
        }
        actual_graph = {
            "graph_pip_count": str(graph_pip_count),
            "graph_pips_sha256": graph_pips_sha256,
        }
        for key, value in expected_graph.items():
            if metadata.get(key) != value or actual_graph[key] != value:
                raise SpecialRouteError(
                    "uarch special-route physical graph identity drift at %s" % key
                )
        if dev_meta.get("n_pips") != str(graph_pip_count):
            raise SpecialRouteError("uarch dev_meta PIP count does not bind the physical graph")
        graph = set(pips_by_name.values())
        missing = catalog.edges - graph
        if missing:
            edge = sorted(missing)[0]
            raise SpecialRouteError("uarch special-route graph drift at %s -> %s" % edge)
        for src, dst in catalog.edges:
            if pips_by_name.get(src + "." + dst) != (src, dst):
                raise SpecialRouteError(
                    "uarch special-route named PIP endpoint drift at %s -> %s" %
                    (src, dst)
                )
        bel_rows = _read_exact_csv(
            devdb / "dev_bels.csv", ("name", "type", "x", "y", "z"),
        )
        bels = {}
        for row in bel_rows:
            if not row.get("name") or row["name"] in bels:
                raise SpecialRouteError("uarch special-route graph has duplicate/empty BEL name")
            bels[row["name"]] = row["type"]
        pin_rows = _read_exact_csv(
            devdb / "dev_belpins.csv", ("bel", "pin", "wire", "dir"),
        )
        pins = {}
        for row in pin_rows:
            key = (row.get("bel"), row.get("pin"))
            if not all(key) or key in pins:
                raise SpecialRouteError("uarch special-route graph has duplicate/empty BEL pin")
            pins[key] = (row["wire"], row["dir"])
        for lane in catalog.lanes:
            expected = (
                (lane.source_bel, "GENERIC_SLICE", lane.source_port,
                 lane.edges[0].src, "out"),
                (lane.sink_bel, "GENERIC_IOB", lane.sink_port,
                 lane.edges[-1].dst, "in"),
            )
            for bel, bel_type, pin, wire, direction in expected:
                if bels.get(bel) != bel_type or pins.get((bel, pin)) != (wire, direction):
                    raise SpecialRouteError(
                        "uarch special-route BEL-pin endpoint drift at %s.%s" %
                        (bel, pin)
                    )
    return metadata["enabled"] == "1", pips_by_name


def validate_devdb(devdb, chipdb_root=None):
    """Validate cache/profile/digest binding and return its enabled flag."""
    return _validated_devdb(devdb, chipdb_root)[0]


def _bits_key(bits):
    return tuple(bit for bit in (bits or ())
                 if isinstance(bit, int) and not isinstance(bit, bool))


def _scalar_integer_bit(bits, what):
    if (not isinstance(bits, list) or len(bits) != 1 or
            not isinstance(bits[0], int) or isinstance(bits[0], bool)):
        raise SpecialRouteError(
            "%s connection must be exactly one integer signal bit" % what
        )
    return bits[0]


def _route_edges(route):
    if route is not None and not isinstance(route, str):
        raise SpecialRouteError("malformed ROUTING attribute (must be text)")
    text = (route or "").strip()
    if not text:
        return set(), set()
    parts = text.split(";")
    if len(parts) % 3:
        raise SpecialRouteError("malformed ROUTING attribute (not wire/pip/strength triples)")
    edges, roots = set(), set()
    triples = set()
    for wire, pip, strength in zip(parts[0::3], parts[1::3], parts[2::3]):
        if not wire:
            raise SpecialRouteError("malformed ROUTING attribute (empty wire)")
        if strength not in {"0", "1", "2", "3", "4", "5", "6"}:
            raise SpecialRouteError(
                "malformed ROUTING attribute (invalid canonical strength %r)" %
                strength
            )
        triple = (wire, pip)
        if triple in triples:
            raise SpecialRouteError("ROUTING contains a duplicate wire/PIP triple")
        triples.add(triple)
        if not pip:
            if wire in roots:
                raise SpecialRouteError("ROUTING contains a duplicate root")
            roots.add(wire)
            continue
        if "." not in pip:
            raise SpecialRouteError("malformed ROUTING PIP %r" % pip)
        src, dst = pip.split(".", 1)
        if dst != wire:
            raise SpecialRouteError("ROUTING PIP destination %s does not match wire %s" %
                                    (dst, wire))
        if (src, dst) in edges:
            raise SpecialRouteError("ROUTING contains a duplicate PIP")
        edges.add((src, dst))
    return edges, roots


def _wire_resource(wire):
    """Return the C++ uarch ``parse_wire`` identity for a serialized wire."""
    tile, separator, resource = wire.rpartition("_")
    if not separator:
        return None
    index = next((offset for offset, char in enumerate(resource)
                  if char.isdigit()), None)
    if index is None:
        return None
    digits = resource[index:]
    if not digits.isdigit():
        return None
    return tile, resource[:index], int(digits)


def _ordinary_static_pip_legal(src, dst, environ=None):
    """Mirror the current C++ static availability gate for imported routes."""
    environ = os.environ if environ is None else environ
    if "AGRV2K_NO_FBBRIDGE" not in environ:
        return True
    source = _wire_resource(src)
    destination = _wire_resource(dst)
    if source is None or destination is None:
        return True
    source_tile, source_resource, source_index = source
    destination_tile, destination_resource, destination_index = destination
    return not (
        source_tile == destination_tile and
        source_resource == destination_resource == "OMUX" and
        source_index % 3 == 2 and destination_index % 3 == 1 and
        source_index // 3 == destination_index // 3
    )


def physical_top_module(document):
    """Resolve the one module consumed by bitgen and every strict validator."""
    modules = document.get("modules") or {}
    if (not isinstance(modules, dict) or not isinstance(modules.get("top"), dict)):
        raise SpecialRouteError("typed special routes require exact modules['top']")
    marked = [
        name for name, module in modules.items()
        if str((module.get("attributes") or {}).get("top", "0"))
        in ("1", "00000000000000000000000000000001")
    ]
    if len(marked) > 1:
        raise SpecialRouteError("routed design marks multiple physical top modules")
    if marked and marked != ["top"]:
        raise SpecialRouteError(
            "physical top marker conflicts with exact modules['top'] emission module"
        )
    return modules["top"]


def _placed_bel(cell, cell_name, relevant_bels):
    attrs = cell.get("attributes") or {}
    surfaces = [(key, attrs[key]) for key in ("BEL", "NEXTPNR_BEL") if key in attrs]
    if not any(value in relevant_bels for _key, value in surfaces):
        return None
    if len({value for _key, value in surfaces}) > 1:
        raise SpecialRouteError("cell %s has conflicting BEL/NEXTPNR_BEL placement" % cell_name)
    if not surfaces:
        return None
    key, value = surfaces[0]
    if not isinstance(value, str) or not value:
        raise SpecialRouteError("cell %s has malformed %s placement" % (cell_name, key))
    return value


def _routing_records(module):
    """Parse every ROUTING carrier and group aliases by exact signal tuple."""
    grouped = {}
    records = []
    netnames = module.get("netnames") or {}
    if not isinstance(netnames, dict):
        raise SpecialRouteError("physical-top netnames must be an object")
    for name, net in netnames.items():
        if not isinstance(net, dict):
            raise SpecialRouteError("netname %s must be an object" % name)
        attrs = net.get("attributes") or {}
        if not isinstance(attrs, dict):
            raise SpecialRouteError("netname %s attributes must be an object" % name)
        route_present = "ROUTING" in attrs
        route = attrs.get("ROUTING")
        if route_present and not isinstance(route, str):
            raise SpecialRouteError(
                "malformed ROUTING attribute on %s (present value must be text)" % name
            )
        raw_bits = net.get("bits")
        signal_bits = (
            isinstance(raw_bits, list) and bool(raw_bits) and
            all(isinstance(bit, int) and not isinstance(bit, bool)
                for bit in raw_bits)
        )
        if route_present and not signal_bits:
            raise SpecialRouteError(
                "ROUTING carrier %s must have a nonempty exact integer signal-bit tuple" % name
            )
        bits = tuple(raw_bits) if signal_bits else ()
        edges, roots = _route_edges(route) if route_present else (set(), set())
        records.append((name, bits, route, edges, roots))
        if not bits:
            continue
        prior = grouped.get(bits)
        if route is not None:
            if prior is not None and prior[1] is not None and prior[1] != route:
                raise SpecialRouteError(
                    "signal aliases for bits %s disagree about ROUTING (%s versus %s)" %
                    (bits, prior[0], name)
                )
            grouped[bits] = (name, route)
        elif prior is None:
            grouped[bits] = (name, None)
    return grouped, tuple(records)


def _validate_routed_snapshot(raw, document, phase, chipdb_root=None, environ=None,
                              devdb=None):
    """Validate one already-loaded routed checkpoint snapshot.

    ``pre-nextpnr`` accepts unresolved placement and empty routes.  Every other
    phase requires full closure for any exact left-output endpoint that exists.
    The one immutable predecessor artifact is accepted without new attributes
    only when its complete file hash matches the published retained hash.
    """
    catalog = load_catalog(chipdb_root)
    module = physical_top_module(document)
    routes, route_records = _routing_records(module)
    strict = phase != "pre-nextpnr"
    legacy = strict and hashlib.sha256(raw).hexdigest() in AUTHENTICATED_RETAINED_SHA256S
    cells = module.get("cells") or {}
    module_attrs = module.get("attributes") or {}

    def one(value):
        return str(value) in ("1", "00000000000000000000000000000001")

    marker_present = any(key in module_attrs for key in (
        MODULE_SCHEMA, TOKEN_CLASS, TOKEN_VERSION, MODULE_DEVICE,
        MODULE_PACKAGE, MODULE_PROFILE, MODULE_ENABLED, TOKEN_DIGEST,
    ))
    token_present = any(
        any(key in (cell.get("attributes") or {})
            for key in (TOKEN_CLASS, TOKEN_VERSION, TOKEN_LANE, TOKEN_DIGEST))
        for cell in cells.values()
    )
    if marker_present:
        expected_marker = {
            TOKEN_CLASS: CLASS, TOKEN_VERSION: ROUTED_VERSION,
            MODULE_DEVICE: DEVICE, MODULE_PACKAGE: PACKAGE,
            MODULE_PROFILE: PROFILE,
            TOKEN_DIGEST: catalog.digest,
        }
        for key, value in expected_marker.items():
            if str(module_attrs.get(key)) != value:
                raise SpecialRouteError("physical-top special-route marker drift at %s" % key)
        if not one(module_attrs.get(MODULE_SCHEMA)):
            raise SpecialRouteError("physical-top special-route marker drift at %s" % MODULE_SCHEMA)
        if MODULE_ENABLED not in module_attrs:
            raise SpecialRouteError("physical-top special-route marker lacks enabled state")
        enabled_text = str(module_attrs[MODULE_ENABLED])
        if enabled_text not in (
            "0", "1",
            "00000000000000000000000000000000",
            "00000000000000000000000000000001",
        ):
            raise SpecialRouteError("physical-top special-route marker has malformed enabled state")
        class_enabled = one(module_attrs[MODULE_ENABLED])
        if not class_enabled and token_present:
            raise SpecialRouteError("disabled special-route profile contains active lane tokens")
    else:
        if token_present:
            raise SpecialRouteError("special-route lane token lacks authenticated physical-top marker")
        class_enabled = legacy

    selected_enabled = expected_enabled(environ)
    if (strict or marker_present) and class_enabled != selected_enabled:
        raise SpecialRouteError(
            "routed special-route enabled state does not match selected device/profile"
        )

    devdb_pips = None
    if class_enabled:
        environ = os.environ if environ is None else environ
        selected_devdb = devdb or environ.get(DEVDB_ENV)
        if not selected_devdb:
            raise SpecialRouteError(
                "active typed special routes require the selected uarch devdb"
            )
        selected_enabled, devdb_pips = _validated_devdb(
            selected_devdb, chipdb_root,
        )
        if selected_enabled is not True:
            raise SpecialRouteError(
                "active typed special routes require an enabled physical-I/O devdb"
            )

    serialized_edges = set()
    for _name, _bits, route_text, route_edges, _route_roots in route_records:
        if route_text is not None:
            serialized_edges.update(route_edges)
    if marker_present and not class_enabled:
        for lane in catalog.lanes:
            lane_edges = {(edge.src, edge.dst) for edge in lane.edges}
            if lane_edges.issubset(serialized_edges):
                raise SpecialRouteError(
                    "disabled special-route profile contains a complete physical lane"
                )
    if not marker_present and not legacy:
        for lane in catalog.lanes:
            lane_edges = {(edge.src, edge.dst) for edge in lane.edges}
            if lane_edges.issubset(serialized_edges):
                raise SpecialRouteError(
                    "complete physical special-route lane lacks authenticated physical-top marker"
                )

    # Generic strict checkpoints explicitly carry enabled=0 and old generic
    # checkpoints carry no marker.  Their 27/36 resources remain ordinary.
    if not class_enabled:
        return {"active_lanes": (), "catalog_sha256": catalog.digest,
                "legacy_retained": False}
    source_bels = frozenset(lane.source_bel for lane in catalog.lanes)
    sink_bels = frozenset(lane.sink_bel for lane in catalog.lanes)

    # Map each bit to its exact placed driver port.  This rejects F on lanes 2/3,
    # even though F and Q share a source OMUX there.
    drivers = {}
    source_occupancy = {lane.source_bel: [] for lane in catalog.lanes}
    for cell_name, cell in cells.items():
        bel = _placed_bel(cell, cell_name, source_bels)
        if bel in source_occupancy:
            source_occupancy[bel].append((cell_name, cell))
        for port, bits in (cell.get("connections") or {}).items():
            for bit in _bits_key(bits):
                drivers.setdefault(bit, []).append((cell_name, bel, port, cell))

    owners = {}
    for lane in catalog.lanes:
        sink_bits = []
        sink_cells = []
        for cell_name, cell in cells.items():
            if _placed_bel(cell, cell_name, sink_bels) == lane.sink_bel:
                sink_cells.append((cell_name, cell))
                if cell.get("type") != "GENERIC_IOB":
                    raise SpecialRouteError("%s lane %d sink is not GENERIC_IOB" %
                                            (CLASS, lane.index))
                if (cell.get("port_directions") or {}).get(lane.sink_port) != "input":
                    raise SpecialRouteError("%s lane %d sink I is not an input" %
                                            (CLASS, lane.index))
                sink_connection = (cell.get("connections") or {}).get(lane.sink_port)
                if sink_connection in (None, []):
                    continue
                sink_bits.append(_scalar_integer_bit(
                    sink_connection,
                    "%s lane %d sink %s.%s" %
                    (CLASS, lane.index, lane.sink_bel, lane.sink_port),
                ))
        if len(sink_cells) > 1:
            raise SpecialRouteError("%s lane %d has duplicate sink BEL occupancy" %
                                    (CLASS, lane.index))
        if not sink_bits:
            continue
        if len(set(sink_bits)) != 1:
            raise SpecialRouteError("%s lane %d has ambiguous sink connection" % (CLASS, lane.index))
        bit = sink_bits[0]
        exact = [item for item in drivers.get(bit, ())
                 if item[1] == lane.source_bel and item[2] == lane.source_port and
                 item[3].get("type") == "GENERIC_SLICE" and
                 (item[3].get("port_directions") or {}).get(lane.source_port) == "output"]
        if len(source_occupancy[lane.source_bel]) != 1:
            raise SpecialRouteError("%s lane %d has non-unique source BEL occupancy" %
                                    (CLASS, lane.index))
        wrong_source_port = [item for item in drivers.get(bit, ())
                             if item[1] == lane.source_bel and item[2] != lane.source_port and
                             (item[3].get("port_directions") or {}).get(item[2]) == "output"]
        if wrong_source_port:
            raise SpecialRouteError("%s lane %d must be driven from %s.%s" %
                                    (CLASS, lane.index, lane.source_bel, lane.source_port))
        if len(source_occupancy[lane.source_bel]) == 1:
            source_cell = source_occupancy[lane.source_bel][0][1]
            source_bit = _scalar_integer_bit(
                (source_cell.get("connections") or {}).get(lane.source_port),
                "%s lane %d source %s.%s" %
                (CLASS, lane.index, lane.source_bel, lane.source_port),
            )
            if source_bit != bit:
                raise SpecialRouteError("%s lane %d lacks its exact %s.%s driver" %
                                        (CLASS, lane.index, lane.source_bel, lane.source_port))
        output_drivers = [item for item in drivers.get(bit, ())
                          if (item[3].get("port_directions") or {}).get(item[2]) == "output"]
        if len(output_drivers) != 1:
            raise SpecialRouteError("%s lane %d has non-unique output driver" %
                                    (CLASS, lane.index))
        if strict and len(exact) != 1:
            raise SpecialRouteError("%s lane %d lacks its exact %s.%s driver" %
                                    (CLASS, lane.index, lane.source_bel, lane.source_port))
        if not exact:
            continue
        owners[lane.index] = (bit, exact[0])

    # Tokens authenticate a reconstructed owner; they never create one.  Audit
    # every token-bearing cell, not only the four cells found above, so a stray
    # or duplicate claim cannot hide on an unrelated cell while the real owner
    # remains valid.
    if strict and not legacy:
        token_keys = (TOKEN_CLASS, TOKEN_VERSION, TOKEN_LANE, TOKEN_DIGEST)
        claims = {}
        for cell_name, cell in cells.items():
            attrs = cell.get("attributes") or {}
            present = [key for key in token_keys if key in attrs]
            if not present:
                continue
            if len(present) != len(token_keys):
                raise SpecialRouteError(
                    "cell %s has a partial special-route lane token" % cell_name
                )
            if attrs[TOKEN_CLASS] != CLASS:
                raise SpecialRouteError(
                    "cell %s has wrong special-route token class" % cell_name
                )
            if str(attrs[TOKEN_VERSION]) != ROUTED_VERSION:
                raise SpecialRouteError(
                    "cell %s has wrong special-route token version" % cell_name
                )
            if attrs[TOKEN_DIGEST] != catalog.digest:
                raise SpecialRouteError(
                    "cell %s has wrong special-route token digest" % cell_name
                )
            lane_text = str(attrs[TOKEN_LANE])
            if lane_text and all(char in "01" for char in lane_text):
                lane_text = str(int(lane_text, 2))
            if lane_text not in {"0", "1", "2", "3"}:
                raise SpecialRouteError(
                    "cell %s has invalid special-route token lane" % cell_name
                )
            lane_index = int(lane_text)
            if lane_index in claims:
                raise SpecialRouteError(
                    "%s lane %d has duplicate token claims" % (CLASS, lane_index)
                )
            claims[lane_index] = cell_name
            owner = owners.get(lane_index)
            if owner is None or owner[1][0] != cell_name:
                raise SpecialRouteError(
                    "cell %s token does not match reconstructed %s lane %d owner" %
                    (cell_name, CLASS, lane_index)
                )

        for lane_index, (_bit, driver) in owners.items():
            if claims.get(lane_index) != driver[0]:
                raise SpecialRouteError(
                    "%s lane %d owner token/digest mismatch: lacks its unique authenticated token" %
                    (CLASS, lane_index)
                )

    active_wires = set().union(*(catalog.lanes[i].wires for i in owners)) if owners else set()
    for lane_index, (bit, driver) in owners.items():
        lane = catalog.lanes[lane_index]
        route_name, route_text = routes.get((bit,), ("bit %d" % bit, None))
        if strict and route_text is None:
            raise SpecialRouteError("%s lane %d net %s has no route" %
                                    (CLASS, lane_index, route_name))
        edges, roots = _route_edges(route_text)
        if strict:
            missing = {(edge.src, edge.dst) for edge in lane.edges} - edges
            if missing:
                edge = sorted(missing)[0]
                raise SpecialRouteError("%s lane %d is incomplete at %s -> %s" %
                                        (CLASS, lane_index, edge[0], edge[1]))
            expected_root = lane.edges[0].src
            if roots != {expected_root}:
                raise SpecialRouteError(
                    "%s lane %d roots %s do not equal exact source root %s" %
                    (CLASS, lane_index, sorted(roots), expected_root)
                )
            reachable = {expected_root}
            while True:
                expanded = reachable.union(
                    dst for src, dst in edges if src in reachable
                )
                if expanded == reachable:
                    break
                reachable = expanded
            disconnected = sorted(
                (src, dst) for src, dst in edges if src not in reachable
            )
            if disconnected:
                src, dst = disconnected[0]
                raise SpecialRouteError(
                    "%s lane %d has edge disconnected from exact source root %s -> %s" %
                    (CLASS, lane_index, src, dst)
                )
        attrs = driver[3].get("attributes") or {}
        if strict and not legacy:
            expected = {
                TOKEN_CLASS: CLASS, TOKEN_VERSION: ROUTED_VERSION,
                TOKEN_LANE: str(lane_index),
                TOKEN_DIGEST: catalog.digest,
            }
            for key, value in expected.items():
                actual = attrs.get(key)
                if key == TOKEN_LANE and isinstance(actual, str) and actual and \
                        all(bit in "01" for bit in actual):
                    actual = str(int(actual, 2))
                if actual != value:
                    raise SpecialRouteError("%s lane %d token/digest mismatch at %s" %
                                            (CLASS, lane_index, key))

        expected_predecessor = {edge.dst: edge.src for edge in lane.edges}
        for src, dst in edges:
            if devdb_pips.get(src + "." + dst) != (src, dst):
                raise SpecialRouteError(
                    "%s lane %d uses PIP absent from selected devdb graph %s -> %s" %
                    (CLASS, lane_index, src, dst)
                )
            if not _ordinary_static_pip_legal(src, dst, environ):
                raise SpecialRouteError(
                    "%s lane %d uses statically unavailable PIP %s -> %s" %
                    (CLASS, lane_index, src, dst)
                )
            touched = {src, dst}.intersection(catalog.wires)
            if not touched:
                continue
            other_lane = next((i for i in range(4) if i != lane_index and
                               touched.intersection(catalog.lanes[i].wires)), None)
            if other_lane is not None:
                raise SpecialRouteError("%s lane %d route touches active lane %d" %
                                        (CLASS, lane_index, other_lane))
            if dst in lane.wires and expected_predecessor.get(dst) != src:
                raise SpecialRouteError("%s lane %d has foreign/re-entry PIP %s -> %s" %
                                        (CLASS, lane_index, src, dst))
            if src in lane.wires and dst in lane.wires and (src, dst) not in catalog.edges:
                raise SpecialRouteError("%s lane %d has non-catalog internal PIP %s -> %s" %
                                        (CLASS, lane_index, src, dst))

    # Any non-owner net touching an active protected resource is foreign.
    owner_keys = {(item[0],) for item in owners.values()}
    for name, bits, route_text, edges, roots in route_records:
        if bits in owner_keys or route_text is None:
            continue
        if roots.intersection(active_wires) or any(
                src in active_wires or dst in active_wires for src, dst in edges):
            raise SpecialRouteError("foreign net %s touches an active %s resource" % (name, CLASS))
    return {"active_lanes": tuple(sorted(owners)), "catalog_sha256": catalog.digest,
            "legacy_retained": legacy}


def load_validated_routed_json(path, phase, chipdb_root=None, environ=None,
                               devdb=None):
    """Read, parse, and validate ``path`` once, returning that exact snapshot.

    Downstream consumers must use ``document`` or ``raw`` from the returned
    object rather than reopening the pathname.  This keeps validation,
    emission, disclosure, and copied artifacts bound to one byte identity.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecialRouteError("cannot read routed design: %s" % exc)
    if not isinstance(document, dict):
        raise SpecialRouteError("routed design must be a JSON object")
    result = _validate_routed_snapshot(
        raw, document, phase, chipdb_root, environ=environ, devdb=devdb,
    )
    return ValidatedRoutedJson(
        raw=raw,
        document=document,
        result=result,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def validate_routed_json(path, phase, chipdb_root=None, environ=None, devdb=None):
    """Compatibility wrapper returning the validation result for one path."""
    return load_validated_routed_json(
        path, phase, chipdb_root, environ=environ, devdb=devdb,
    ).result
