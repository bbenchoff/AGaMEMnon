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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agamemnon.engine.registry import options_from
from agamemnon.engine.slice_profiles import direct_d_arch_sites


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
EXPECTED_PHYSICAL_GRAPH_PIP_COUNT = 248310
EXPECTED_PHYSICAL_GRAPH_SHA256 = (
    # Five vendor-observed high-address logic edges; removing exactly those
    # additions reproduces the previous pinned graph byte-for-byte. All
    # physical-owner touching edges are unchanged. See docs/mcu_haddr_region_logic.md.
    "46bea5556598f30010ae30cbc172f81f4eda4f6d8d879c71ceef4c7589816f81"
)
EXPECTED_TIERED_PHYSICAL_GRAPH_PIP_COUNT = 326271
EXPECTED_TIERED_PHYSICAL_GRAPH_SHA256 = (
    # Same five additions and byte-exact reverse-delta check as strict.
    # Graph identity is not conduction qualification of tier-2 routes.
    "8ff4c97f71118b3ccbbdc8b535b81eb28a8996dc2ce569a29fbdc2fb91eac1a4"
)
EXPECTED_PHYSICAL_GRAPHS = {
    "release-strict": (
        EXPECTED_PHYSICAL_GRAPH_PIP_COUNT,
        EXPECTED_PHYSICAL_GRAPH_SHA256,
    ),
    "tiered": (
        EXPECTED_TIERED_PHYSICAL_GRAPH_PIP_COUNT,
        EXPECTED_TIERED_PHYSICAL_GRAPH_SHA256,
    ),
}
# Marker migration is intentionally hash-only.  These immutable routed inputs
# predate the typed special-route module markers and are already pinned in
# qualification/pack_regression.json.  The three SERV rows are also bound by
# qualification/serv_compliance_evidence.jsonl, and the four-lane row is bound
# by left_edge_output_evidence.jsonl.  No path, filename, or merely
# topologically similar copy receives this exception.
LEGACY_RETAINED_SHA256 = (
    "b2ac1448106262a71bba927f03e262808adf620c49aa310a06f12f1ee76f3d3c"
)
AUTHENTICATED_RETAINED_SHA256S = frozenset({
    "2fbb058fdfc8a054917aba6e9d0b3bae5a9164b3bbfe962c4c05b7042493d805",
    "e3cec1567e1dbcd6aafb9b734407c13b8c3e469fced23ac84eb62286eecaf576",
    "4ffe1076ce65a9a2e0bbbdcbeb67900c6c6249367b3c4f7da41210fdec4563d2",
    "a6bd7af0038ceaedc6134c446b5a58801e336a50ad5820eb4e10f1aed9a3d830",
    "3ba005c8d8a48dcb48e87573fbee83072eefc9c0383a80e729585a4f61f568d5",
    "a8bc5940fd5c2bd18e6622fa21b39a0d78bd29cecf7a9480bdb8b7bbc6a9c55c",
    "48438cf5a6b35b2ee2d57be42299d40fac1ba3134f8696f43f20b12b39d6ae9a",
    "00eb1537293d28e4547a69bedbf16158f12cf520b45e68af9760ccfd92881b43",
    "b512d1b6d183fd5c5b81229aa7c2297362a5aa222a05d62edee4eb18e42d8b85",
    "d20fd1734bb991042d8e622852be7d87f361d2788fb53057cbd35b3615b34e57",
    "424007afbbad74d267f11a036900123f1722811b1089b3921830b8e7db377234",
    "07cbbe31ddba7c1943375570652371c8d0baf995b0bf151aa87600d5492424a2",
    LEGACY_RETAINED_SHA256,
    "bf1523f0b54c54119b6debd8909613db03ede4c38ca36b254fd5ad479c8d3f59",
    "8670571959a469e5f401cd1585ec601419b686a3a7294cb84f8b0e3be5393a53",
    "653548276f85a45e1bb618eef06a38ba0a456a8032b3f34281f2fb6e2fec469b",
    "589fa824da97b77ab45e6a06ae21999481add8bc99272dec1613fa42d9abe96f",
    "128e679934732efbe73d743b3a9a5af44f3fae2c19648a4d29c6cc4054d01075",
})

# The exact four-lane predecessor intentionally fed one separately placed
# observation buffer per lane as well as the pad.  Its immutable canonical
# hash authenticates the complete checkpoint, while these endpoints make the
# one permitted legacy fanout shape explicit and independently reviewable.
LEGACY_RETAINED_FABRIC_FANOUTS = (
    ("X16Y11_SLICE0", "I"),
    ("X14Y10_SLICE0", "I"),
    ("X14Y10_SLICE2", "I"),
    ("X16Y11_SLICE2", "I"),
)
LEGACY_RETAINED_FABRIC_EDGES = (
    frozenset({
        ("X14Y11_OMUX12", "X15Y11_RMUX31"),
        ("X15Y11_RMUX31", "X16Y11_RMUX41"),
        ("X16Y11_RMUX41", "X16Y11_IMUX03"),
    }),
    frozenset({
        ("X14Y11_OMUX15", "X15Y11_RMUX33"),
        ("X15Y11_RMUX33", "X14Y11_RMUX39"),
        ("X14Y11_RMUX39", "X14Y10_RMUX53"),
        ("X14Y10_RMUX53", "X14Y10_IMUX03"),
    }),
    frozenset({
        ("X14Y11_RMUX44", "X14Y10_RMUX75"),
        ("X14Y10_RMUX75", "X14Y11_RMUX21"),
        ("X14Y11_RMUX21", "X14Y10_RMUX83"),
        ("X14Y10_RMUX83", "X14Y10_IMUX11"),
    }),
    frozenset({
        ("X14Y11_OMUX23", "X14Y11_RMUX31"),
        ("X14Y11_RMUX31", "X16Y11_RMUX47"),
        ("X16Y11_RMUX47", "X16Y11_IMUX11"),
    }),
)

SOURCE_FRESH_PHYSICAL_ENV = (
    "AGAMEMNON_CONDUCTION_GATE=1",
    "AGAMEMNON_HW_CARRY=1",
    "AGAMEMNON_LEDPADS=1",
    "AGAMEMNON_STRICT_GATE=1",
    "AGAMEMNON_XBAR_CONDUCT=1",
    "AGAMEMNON_CLEAN_SEL_GATE=1",
    "AGAMEMNON_PHYSICAL_IO=1",
    "AGAMEMNON_PADFEED_TOP=1",
    "AGAMEMNON_HARDEN_PADFEED=1",
    "AGAMEMNON_LEFT_PAD_OUT=1",
)

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


def split_env_summary(text):
    r"""Split the record on UNESCAPED semicolons.

    Three registered options -- AGAMEMNON_DIRECT_D_SITES,
    AGAMEMNON_DIRECT_D_EXTRA_SITES and AGAMEMNON_VENDOR_OUT_SLICE -- hold
    semicolon-separated lists, which is the same character this record uses to
    separate its own fields.  Before escaping, a two-site direct-D value turned
    every site after the first into a token with no "=" and the whole record was
    rejected as malformed, so no multi-site direct-D build could complete.  The
    writer in emit_uarch_db escapes a backslash as "\\" and a semicolon as
    "\;"; this reverses that.  A value containing neither is byte-identical
    either way, so every profile that worked before is unaffected.
    """
    tokens = []
    current = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == chr(92):
            escaped = True
        elif char == ";":
            tokens.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        raise SpecialRouteError("uarch agamemnon_env summary ends in a dangling escape")
    tokens.append("".join(current))
    return tokens


def _parse_env_summary(text):
    """Parse the exact semicolon-separated device-cache environment record."""
    if not text:
        return {}
    parsed = {}
    for token in split_env_summary(text):
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
    try:
        direct_sites = direct_d_arch_sites(options_from(env))
    except ValueError as exc:
        raise SpecialRouteError(str(exc)) from exc
    available_lanes = set()
    physical = (env.get("AGAMEMNON_PHYSICAL_IO") == "1" and
                env.get("AGAMEMNON_LEFT_PAD_OUT") == "1")
    if (metadata["enabled"] == "1") != physical:
        raise SpecialRouteError("uarch special-route profile/cache mismatch")
    pips_by_name = None
    if metadata["enabled"] == "1":
        pips_by_name, graph_pip_count, graph_pips_sha256 = _devdb_pips(devdb)
        admission = env.get("AGAMEMNON_ROUTING_ADMISSION", "release-strict")
        try:
            expected_pip_count, expected_pips_sha256 = EXPECTED_PHYSICAL_GRAPHS[admission]
        except KeyError:
            raise SpecialRouteError(
                "uarch special-route physical graph has unknown routing admission %r" %
                admission
            )
        expected_graph = {
            "graph_pip_count": str(expected_pip_count),
            "graph_pips_sha256": expected_pips_sha256,
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
            # Only modeled direct-D presentations may differ from the fixed
            # catalog. Unknown endpoint drift remains fatal on unused lanes.
            source_wire = lane.edges[0].src
            for z in (6, 7):
                if (lane.source_bel == "X14Y11_SLICE%d" % z and
                        (14, 11, z) in direct_sites):
                    source_wire = "X14Y11_OMUX%02d" % (3 * z + 1)
            if source_wire == lane.edges[0].src:
                available_lanes.add(lane.index)
            expected = (
                (lane.source_bel, "GENERIC_SLICE", lane.source_port,
                 source_wire, "out"),
                (lane.sink_bel, "GENERIC_IOB", lane.sink_port,
                 lane.edges[-1].dst, "in"),
            )
            for bel, bel_type, pin, wire, direction in expected:
                if bels.get(bel) != bel_type or pins.get((bel, pin)) != (wire, direction):
                    raise SpecialRouteError(
                        "uarch special-route BEL-pin endpoint drift at %s.%s" %
                        (bel, pin)
                    )
    return metadata["enabled"] == "1", pips_by_name, frozenset(available_lanes)


def validate_devdb(devdb, chipdb_root=None):
    """Validate cache/profile/digest binding and return its enabled flag."""
    return _validated_devdb(devdb, chipdb_root)[0]


def emit_source_fresh_physical_devdb(out_dir, chipdb_root=None):
    """Build and validate the exact strict physical-I/O graph from source.

    The caller must provide an absent or empty output directory.  Ambient
    AGAMEMNON_* state is removed; the complete reviewed graph profile above is
    supplied explicitly.  Failure to build or validate is fatal rather than a
    reason to reuse an inherited cache.
    """
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SpecialRouteError(
            "source-fresh physical devdb output directory is not empty: %s" % out_dir
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = Path(__file__).resolve().parent
    chipdb_root = catalog_path(chipdb_root).parent
    command = [
        sys.executable,
        str(engine / "emit_uarch_db.py"),
        "--arch", str(engine / "arch.py"),
        "--data", str(chipdb_root),
        "--out", str(out_dir),
    ]
    for item in SOURCE_FRESH_PHYSICAL_ENV:
        command.extend(("--env", item))
    clean_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("AGAMEMNON_")
    }
    try:
        result = subprocess.run(
            command, cwd=engine.parents[1], env=clean_env,
            capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpecialRouteError(
            "cannot build source-fresh physical devdb: %s" % exc
        ) from exc
    if result.returncode != 0:
        diagnostic = (result.stdout + result.stderr)[-4000:]
        raise SpecialRouteError(
            "source-fresh physical devdb build failed: %s" % diagnostic
        )
    if validate_devdb(out_dir, chipdb_root) is not True:
        raise SpecialRouteError(
            "source-fresh physical devdb did not enable the exact profile"
        )
    return out_dir


def _canonical_routed_sha256(raw):
    """Match pack_regression.json's canonical-LF routed identity."""
    canonical = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


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


def _known_connected_port_direction(cell_type, port):
    """Return the architecture-defined direction for a known fabric port."""
    if cell_type == "GENERIC_SLICE":
        if port in {"F", "Q", "COUT"}:
            return "output"
        if port in {"A", "B", "C", "D", "CLK", "I", "CIN"}:
            return "input"
        if port.startswith("I[") and port.endswith("]") and port[2:-1].isdigit():
            return "input"
        return False
    if cell_type == "GENERIC_IOB":
        return {"I": "input", "EN": "input", "O": "output", "PAD": "inout"}.get(
            port, False,
        )
    return None


def _validated_connected_port_direction(cell_name, cell, port):
    """Validate direction metadata for a port already known to be connected."""
    directions = cell.get("port_directions")
    if not isinstance(directions, dict) or port not in directions:
        raise SpecialRouteError(
            "connected port direction metadata is missing or malformed at %s.%s" %
            (cell_name, port)
        )
    direction = directions[port]
    if direction not in {"input", "output", "inout"}:
        raise SpecialRouteError(
            "connected port direction metadata is unknown at %s.%s" %
            (cell_name, port)
        )
    known = _known_connected_port_direction(cell.get("type"), port)
    if known is False:
        raise SpecialRouteError(
            "connected port direction metadata names unknown %s port %s.%s" %
            (cell.get("type"), cell_name, port)
        )
    if known is not None and direction != known:
        raise SpecialRouteError(
            "connected port direction metadata contradicts known %s semantics at %s.%s" %
            (cell.get("type"), cell_name, port)
        )
    return direction


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
    routed_identity = _canonical_routed_sha256(raw)
    legacy = strict and routed_identity in AUTHENTICATED_RETAINED_SHA256S
    selected_enabled = expected_enabled(environ)
    selected_devdb = devdb or options_from(environ).raw(
        "AGAMEMNON_SPECIAL_ROUTE_DEVDB"
    )
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
        # Exact pre-marker checkpoints remain replayable under their recorded
        # historical environment, where these wires were emitted as ordinary
        # routing.  Selecting the physical profile together with an exact
        # device database promotes that same immutable checkpoint into full
        # typed-route validation; the hash alone never selects either one.
        class_enabled = legacy and selected_enabled and bool(selected_devdb)

    historical_legacy_replay = (
        legacy and not marker_present and not selected_devdb
    )
    if ((strict or marker_present) and class_enabled != selected_enabled
            and not historical_legacy_replay):
        raise SpecialRouteError(
            "routed special-route enabled state does not match selected device/profile"
        )

    devdb_pips = None
    if class_enabled:
        if not selected_devdb:
            raise SpecialRouteError(
                "active typed special routes require the selected uarch devdb"
            )
        selected_enabled, devdb_pips, available_lanes = _validated_devdb(
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
    endpoint_bels = source_bels.union(sink_bels)

    # Index every connected endpoint independently of untrusted direction
    # metadata.  Direction is validated only after an active owner bit is
    # identified, so malformed unrelated ports cannot broaden this classifier.
    endpoints = {}
    source_occupancy = {lane.source_bel: [] for lane in catalog.lanes}
    for cell_name, cell in cells.items():
        bel = _placed_bel(cell, cell_name, endpoint_bels)
        if bel in source_occupancy:
            source_occupancy[bel].append((cell_name, cell))
        for port, bits in (cell.get("connections") or {}).items():
            for bit in _bits_key(bits):
                record = (cell_name, bel, port, cell)
                endpoints.setdefault(bit, []).append(record)

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
                sink_connection = (cell.get("connections") or {}).get(lane.sink_port)
                if sink_connection in (None, []):
                    continue
                if _validated_connected_port_direction(
                        cell_name, cell, lane.sink_port) != "input":
                    raise SpecialRouteError("%s lane %d sink I is not an input" %
                                            (CLASS, lane.index))
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
        if lane.index not in available_lanes:
            raise SpecialRouteError(
                "%s lane %d is incompatible with the selected direct-D graph profile" %
                (CLASS, lane.index)
            )
        if len(set(sink_bits)) != 1:
            raise SpecialRouteError("%s lane %d has ambiguous sink connection" % (CLASS, lane.index))
        bit = sink_bits[0]
        directed_endpoints = [
            (item, _validated_connected_port_direction(item[0], item[3], item[2]))
            for item in endpoints.get(bit, ())
        ]
        exact = [item for item, direction in directed_endpoints
                 if item[1] == lane.source_bel and item[2] == lane.source_port and
                 item[3].get("type") == "GENERIC_SLICE" and
                 direction == "output"]
        if len(source_occupancy[lane.source_bel]) != 1:
            raise SpecialRouteError("%s lane %d has non-unique source BEL occupancy" %
                                    (CLASS, lane.index))
        wrong_source_port = [item for item, direction in directed_endpoints
                             if item[1] == lane.source_bel and item[2] != lane.source_port and
                             direction == "output"]
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
        output_drivers = [item for item, direction in directed_endpoints
                          if direction == "output"]
        if len(output_drivers) != 1:
            raise SpecialRouteError("%s lane %d has non-unique output driver" %
                                    (CLASS, lane.index))
        users = [item for item, direction in directed_endpoints
                 if direction in ("input", "inout")]
        pad_users = [item for item in users
                     if item[1] == lane.sink_bel and item[2] == lane.sink_port and
                     item[3].get("type") == "GENERIC_IOB"]
        if routed_identity == LEGACY_RETAINED_SHA256:
            expected_fanout = LEGACY_RETAINED_FABRIC_FANOUTS[lane.index]
            fabric_users = [
                item for item in users
                if _placed_bel(
                    item[3], item[0], frozenset((expected_fanout[0],))
                ) == expected_fanout[0] and item[2] == expected_fanout[1] and
                item[3].get("type") == "GENERIC_SLICE"
            ]
            if len(users) != 2 or len(pad_users) != 1 or len(fabric_users) != 1:
                raise SpecialRouteError(
                    "%s lane %d exact retained observation fanout drift" %
                    (CLASS, lane.index)
                )
        elif len(users) != 1 or len(pad_users) != 1:
            raise SpecialRouteError(
                "%s lane %d owner must be pad-only; additional fabric users are unsupported" %
                (CLASS, lane.index)
            )
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
        legacy_fabric_edges = (
            LEGACY_RETAINED_FABRIC_EDGES[lane_index]
            if routed_identity == LEGACY_RETAINED_SHA256 else frozenset()
        )
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
            if (src, dst) not in catalog.edges and (src, dst) not in legacy_fabric_edges:
                raise SpecialRouteError(
                    "%s lane %d has unsupported non-catalog departure %s -> %s" %
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
