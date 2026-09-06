"""Digest-bound GCLK0 source and generated-topology authority for N5.7A."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


SCHEMA = "1"
VERSION = "1"
CLASS = "GCLK0"
DEVICE = "AGRV2KL48"
PACKAGE = "L48"
SPINE = "GCLK0"
WIRE_TYPE = "GCLK0_SPINE"
ENTRY_TYPE = "GCLK0_ENTRY"
SLICE_LEAF_TYPE = "GCLK0_SLICE_LEAF"
BRAM_ROOT_TYPE = "GCLK0_BRAM_ROOT"
BRAM_BRANCH_TYPE = "GCLK0_BRAM_BRANCH"
SOURCE_CATALOG_NAME = "clock_source_profiles_l48.csv"
LEGACY_QUARANTINE_NAME = "clock_legacy_extra_leaves.json"
DEV_SOURCE_NAME = "dev_clock_sources.csv"
DEV_META_NAME = "dev_clock_meta.csv"
EXPECTED_SOURCE_CATALOG_SHA256 = (
    "0166c3d2eaec1bc7e2832b33d6e7d9afcfb79d23c5d4f185762bf6356d53b1cd"
)
EXPECTED_TOPOLOGY_SHA256 = (
    "b0ac7c2d5e93b5c922610d6528e5f785d81ad7d420df99ac29c8c74adcf4b505"
)
LEGACY_TOPOLOGY_SHA256 = "57c7c819bf1ccddbe16243f2349597620743f047b6f2ccbc133378d44043f26d"
SOURCE_FIELDS = (
    "schema", "device", "package", "profile", "source_class", "version",
    "admitted", "cell_type", "bel", "port", "root_wire", "entry_src",
    "entry_dst", "rate_policy", "evidence",
)
EXPECTED_COUNTS = {
    "source_count": "3", "admitted_source_count": "2", "entry_count": "46",
    "slice_leaf_count": "2112", "bram_root_count": "1",
    "bram_branch_count": "4",
}
BRAM_ROOT_EDGE = ("GCLK0", "X13Y0_BufMUX05")
BRAM_BRANCH_EDGES = frozenset({
    ("X13Y0_BufMUX05", "X13Y3_SeamMUX01"),
    ("X13Y3_SeamMUX01", "X13Y3_TileClkMUX01"),
    ("X13Y0_BufMUX05", "X13Y4_SeamMUX01"),
    ("X13Y4_SeamMUX01", "X13Y4_TileClkMUX01"),
})
BRAM_SITES = frozenset({"X13Y3_BRAM", "X13Y4_BRAM"})

def bram_branch_edges(bel):
    if bel not in BRAM_SITES:
        raise ClockResourceError("GCLK0 resources: unsupported BRAM clock site %s" % bel)
    prefix = bel.removesuffix("_BRAM")
    return frozenset({("X13Y0_BufMUX05", prefix + "_SeamMUX01"),
                      (prefix + "_SeamMUX01", prefix + "_TileClkMUX01")})
_LEAF = re.compile(r"X(\d+)Y(\d+)_ClkMUX(\d{2})")


class ClockResourceError(ValueError):
    """Clock metadata or a generated device topology failed closed."""


@dataclass(frozen=True)
class ClockSourceProfile:
    profile: str
    source_class: str
    cell_type: str
    bel: str
    port: str
    root_wire: str
    entry_edge: tuple[str, str] | None
    admitted: bool
    rate_policy: str
    evidence: str


@dataclass(frozen=True)
class ClockCatalog:
    rows: tuple[dict[str, str], ...]
    profiles: tuple[ClockSourceProfile, ...]
    digest: str

    def by_id(self, name):
        return next((profile for profile in self.profiles
                     if profile.profile == name), None)


def _reject(reason):
    raise ClockResourceError("GCLK0 resources: %s" % reason)


def chipdb_path(name, chipdb_root=None):
    root = (Path(__file__).resolve().parents[1] / "chipdb"
            if chipdb_root is None else Path(chipdb_root))
    return root / name


def _read_csv(path, fields):
    try:
        with Path(path).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != tuple(fields):
                _reject("%s has wrong columns" % path)
            rows = []
            for index, row in enumerate(reader, 1):
                if set(row) != set(fields) or any(row[key] is None for key in fields):
                    _reject("%s row %d is malformed" % (path, index))
                rows.append(dict(row))
            return tuple(rows)
    except OSError as exc:
        _reject("cannot read %s: %s" % (path, exc))


def _canonical_source_bytes(rows):
    lines = [",".join(SOURCE_FIELDS)]
    lines.extend(",".join(row[field] for field in SOURCE_FIELDS) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def load_source_catalog(chipdb_root=None):
    path = chipdb_path(SOURCE_CATALOG_NAME, chipdb_root)
    rows = _read_csv(path, SOURCE_FIELDS)
    digest = hashlib.sha256(_canonical_source_bytes(rows)).hexdigest()
    if digest != EXPECTED_SOURCE_CATALOG_SHA256:
        _reject("source catalog digest is not the reviewed N5.7A authority")
    if len(rows) != 3 or len({row["profile"] for row in rows}) != 3:
        _reject("source catalog must contain exactly three unique profiles")
    expected = {
        "HSE_PLL_CLKIN_V1": ("HSE_PLL", "GENERIC_IOB", "CLKIN", "O", "1"),
        "MCU_BUS_DEFAULT_V1": (
            "MCU_BUS", "MCU_BUS_CLOCK", "X10Y5_MCU_BUS_CLOCK", "CLK", "1"
        ),
        "MCU_SYS_UNSUPPORTED_V1": (
            "MCU_SYS", "MCU_SYS_CLOCK", "X10Y5_MCU_SYS_CLOCK", "CLK", "0"
        ),
    }
    profiles = []
    for row in rows:
        if (row["schema"], row["device"], row["package"], row["version"]) != (
                SCHEMA, DEVICE, PACKAGE, VERSION):
            _reject("profile %s has wrong fixed identity" % row["profile"])
        identity = (row["source_class"], row["cell_type"], row["bel"],
                    row["port"], row["admitted"])
        if expected.get(row["profile"]) != identity:
            _reject("profile %s has wrong endpoint/admission identity" % row["profile"])
        if bool(row["entry_src"]) != bool(row["entry_dst"]):
            _reject("profile %s has a partial entry edge" % row["profile"])
        entry = ((row["entry_src"], row["entry_dst"])
                 if row["entry_src"] else None)
        if entry is not None and (entry[0] != row["root_wire"] or entry[1] != SPINE):
            _reject("profile %s entry does not terminate at GCLK0" % row["profile"])
        if entry is None and row["root_wire"] != SPINE:
            _reject("direct profile %s must root at GCLK0" % row["profile"])
        profiles.append(ClockSourceProfile(
            row["profile"], row["source_class"], row["cell_type"], row["bel"],
            row["port"], row["root_wire"], entry, row["admitted"] == "1",
            row["rate_policy"], row["evidence"],
        ))
    return ClockCatalog(rows, tuple(profiles), digest)


def _graph_topology(graph_wires, graph_pips):
    wires = []
    for row in graph_wires:
        name, kind = row[0], row[1]
        if kind == WIRE_TYPE or name == SPINE:
            wires.append((str(name), str(kind)))
    pips = []
    clock_types = {ENTRY_TYPE, SLICE_LEAF_TYPE, BRAM_ROOT_TYPE, BRAM_BRANCH_TYPE}
    for row in graph_pips:
        _name, kind, src, dst = row[:4]
        if kind in clock_types or str(kind).startswith("GCLK0_"):
            pips.append((str(kind), str(src), str(dst)))
    if wires != [(SPINE, WIRE_TYPE)]:
        _reject("generated graph must contain exactly one typed GCLK0 spine")
    typed = {kind: [] for kind in clock_types}
    for kind, src, dst in pips:
        if kind not in typed:
            _reject("generated graph contains unsupported clock PIP type %s" % kind)
        typed[kind].append((src, dst))
    if len(typed[ENTRY_TYPE]) != 46:
        _reject("generated graph must contain exactly 46 GCLK0 entries")
    if len(typed[SLICE_LEAF_TYPE]) != 2112:
        _reject("generated graph must contain exactly 2,112 slice leaves")
    if typed[BRAM_ROOT_TYPE] != [BRAM_ROOT_EDGE]:
        _reject("generated graph has wrong GCLK0 BRAM root")
    if frozenset(typed[BRAM_BRANCH_TYPE]) != BRAM_BRANCH_EDGES or len(
            typed[BRAM_BRANCH_TYPE]) != len(BRAM_BRANCH_EDGES):
        _reject("generated graph has wrong GCLK0 BRAM branches")
    if any(dst != SPINE for _src, dst in typed[ENTRY_TYPE]):
        _reject("a GCLK0 entry does not terminate at the spine")
    if len(set(typed[ENTRY_TYPE])) != 46:
        _reject("generated graph contains duplicate GCLK0 entries")
    leaves = set()
    tile_sites = {}
    for src, dst in typed[SLICE_LEAF_TYPE]:
        match = _LEAF.fullmatch(dst)
        if src != SPINE or match is None or not 0 <= int(match.group(3)) < 16:
            _reject("generated graph contains malformed slice leaf %s -> %s" % (src, dst))
        if dst in leaves:
            _reject("generated graph contains duplicate slice leaf %s" % dst)
        leaves.add(dst)
        tile_sites.setdefault((int(match.group(1)), int(match.group(2))), set()).add(
            int(match.group(3))
        )
    if len(tile_sites) != 132 or any(sites != set(range(16))
                                     for sites in tile_sites.values()):
        _reject("slice leaves are not exact 132-by-16 tile/site coverage")
    records = [("wire", WIRE_TYPE, SPINE, "")]
    records.extend(("pip", kind, src, dst) for kind, src, dst in pips)
    canonical = "".join("\t".join(row) + "\n" for row in sorted(records)).encode()
    return hashlib.sha256(canonical).hexdigest(), typed


def emit_devdb_metadata(out_dir, chipdb_root=None, graph_wires=(), graph_pips=()):
    catalog = load_source_catalog(chipdb_root)
    topology_sha256, typed = _graph_topology(graph_wires, graph_pips)
    if topology_sha256 != EXPECTED_TOPOLOGY_SHA256:
        _reject("generated graph topology is not the reviewed N5.7A authority")
    out_dir = Path(out_dir)
    with (out_dir / DEV_SOURCE_NAME).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SOURCE_FIELDS)
        writer.writeheader(); writer.writerows(catalog.rows)
    metadata = (
        ("schema", SCHEMA), ("class", CLASS), ("version", VERSION),
        ("device", DEVICE), ("package", PACKAGE), ("spine", SPINE),
        ("wire_type", WIRE_TYPE), ("entry_type", ENTRY_TYPE),
        ("slice_leaf_type", SLICE_LEAF_TYPE), ("bram_root_type", BRAM_ROOT_TYPE),
        ("bram_branch_type", BRAM_BRANCH_TYPE),
        ("source_count", str(len(catalog.profiles))),
        ("admitted_source_count", str(sum(p.admitted for p in catalog.profiles))),
        ("entry_count", str(len(typed[ENTRY_TYPE]))),
        ("slice_leaf_count", str(len(typed[SLICE_LEAF_TYPE]))),
        ("bram_root_count", str(len(typed[BRAM_ROOT_TYPE]))),
        ("bram_branch_count", str(len(typed[BRAM_BRANCH_TYPE]))),
        ("source_catalog_sha256", catalog.digest),
        ("topology_sha256", topology_sha256),
    )
    with (out_dir / DEV_META_NAME).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream); writer.writerow(("key", "value")); writer.writerows(metadata)
    return dict(metadata)


def _metadata(path):
    rows = _read_csv(path, ("key", "value"))
    result = {}
    for row in rows:
        if not row["key"] or row["key"] in result:
            _reject("%s has duplicate/empty keys" % path)
        result[row["key"]] = row["value"]
    return result


def validate_devdb(devdb, chipdb_root=None):
    devdb = Path(devdb)
    catalog = load_source_catalog(chipdb_root)
    source_rows = _read_csv(devdb / DEV_SOURCE_NAME, SOURCE_FIELDS)
    if source_rows != catalog.rows:
        _reject("generated source catalog differs from checked-in authority")
    meta = _metadata(devdb / DEV_META_NAME)
    fixed = {
        "schema": SCHEMA, "class": CLASS, "version": VERSION, "device": DEVICE,
        "package": PACKAGE, "spine": SPINE, "wire_type": WIRE_TYPE,
        "entry_type": ENTRY_TYPE, "slice_leaf_type": SLICE_LEAF_TYPE,
        "bram_root_type": BRAM_ROOT_TYPE, "bram_branch_type": BRAM_BRANCH_TYPE,
        "source_catalog_sha256": catalog.digest, **EXPECTED_COUNTS,
    }
    expected_meta_keys = set(fixed) | {"topology_sha256"}
    if set(meta) != expected_meta_keys:
        _reject("generated clock metadata has missing or extra keys")
    for key, value in fixed.items():
        if meta[key] != value:
            _reject("generated clock metadata drift at %s" % key)
    wires = _read_csv(devdb / "dev_wires.csv", ("name", "type", "x", "y"))
    pips = _read_csv(
        devdb / "dev_pips.csv",
        ("name", "type", "src", "dst", "delay_ns", "x", "y", "z"),
    )
    topology_sha256, _typed = _graph_topology(
        [(row["name"], row["type"]) for row in wires],
        [(row["name"], row["type"], row["src"], row["dst"]) for row in pips],
    )
    if topology_sha256 != EXPECTED_TOPOLOGY_SHA256:
        _reject("generated graph topology is not the reviewed N5.7A authority")
    if meta.get("topology_sha256") != topology_sha256:
        _reject("generated clock topology digest drift")
    dev_meta = _metadata(devdb / "dev_meta.csv")
    expected_binding = {
        "clock_class": CLASS,
        "clock_source_catalog_sha256": catalog.digest,
        "clock_topology_sha256": topology_sha256,
    }
    for key, value in expected_binding.items():
        if dev_meta.get(key) != value:
            _reject("dev_meta clock binding drift at %s" % key)
    return meta
