"""Fail-closed contract for row-tiered experimental routing selectors.

The release selector database is admitted as one individually-qualified
surface and must never receive differential-only rows.  This module defines a
separate exact-row format and resolves explicit experimental selections for
both architecture construction and bitstream emission.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from .registry import ClaimMetadata, POLICY_VERSION


FILENAME = "routing_selector_admission.json"
SCHEMA = "agamemnon.routing-selector-admission.v1"
OPTION_NAME = "AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FAMILY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
CFG = re.compile(r"^CFG_[A-Za-z0-9_]+$")


class RoutingAdmissionError(RuntimeError):
    """The experimental routing admission contract failed closed."""


def _require(condition, message):
    if not condition:
        raise RoutingAdmissionError(message)


def canonical_identity(row):
    body = dict(row)
    body.pop("row_identity", None)
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def canonical_value_identity(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def canonical_edge_id(route):
    source = route["source"]
    destination = route["destination"]
    text = (
        "%s%d@%d,%d->%s%d@%d,%d"
        % (
            source["family"], source["index"], source["x"], source["y"],
            destination["family"], destination["index"],
            destination["x"], destination["y"],
        )
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def canonical_dossier_identity(value):
    _require(isinstance(value, dict) and "dossier_identity" in value,
             "routing dossier has no canonical identity")
    declared = value["dossier_identity"]
    _require(isinstance(declared, str) and SHA256.fullmatch(declared),
             "routing dossier canonical identity is invalid")
    body = dict(value)
    del body["dossier_identity"]
    computed = canonical_value_identity(body)
    _require(computed == declared, "routing dossier identity mismatch")
    return computed


def _component(value, label):
    fields = {"tile", "x", "y", "family", "index"}
    _require(isinstance(value, dict) and set(value) == fields,
             "%s field set mismatch" % label)
    _require(isinstance(value["tile"], str) and value["tile"],
             "%s tile is invalid" % label)
    _require(isinstance(value["family"], str) and FAMILY.fullmatch(value["family"]),
             "%s family is invalid" % label)
    for name in ("x", "y", "index"):
        _require(isinstance(value[name], int) and 0 <= value[name] <= 4095,
                 "%s %s is invalid" % (label, name))


def _reference(value, label):
    _require(isinstance(value, dict) and set(value) == {"path", "sha256"},
             "%s field set mismatch" % label)
    path = Path(value["path"])
    _require(isinstance(value["path"], str) and value["path"]
             and not path.is_absolute() and ".." not in path.parts
             and "\\" not in value["path"],
             "%s must be a safe public relative reference" % label)
    _require(isinstance(value["sha256"], str) and SHA256.fullmatch(value["sha256"]),
             "%s hash is invalid" % label)


def _verify_reference(chipdb_root, value, label):
    _reference(value, label)
    root = Path(chipdb_root).resolve()
    path = (root / value["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RoutingAdmissionError("%s resolves outside chipdb" % label) from exc
    _require(path.is_file(), "%s is missing" % label)
    _require(hashlib.sha256(path.read_bytes()).hexdigest() == value["sha256"],
             "%s hash mismatch" % label)
    return path


def _validate_row(row):
    fields = {
        "feature_id", "edge_id", "row_identity", "route", "encoding",
        "registry_maturity", "evidence_tier", "claim_domain",
        "strict_permission", "scope", "evidence_refs", "approval",
        "conflict_count", "unknown_count", "terminal_edge_overlap_count",
        "retained_negative_refs",
    }
    _require(isinstance(row, dict) and set(row) == fields,
             "routing admission row field set mismatch")
    _require(isinstance(row["edge_id"], str) and SHA256.fullmatch(row["edge_id"]),
             "routing admission edge_id is invalid")
    _require(row["feature_id"] == OPTION_NAME,
             "routing admission feature_id does not bind the registered option")
    _require(isinstance(row["row_identity"], str)
             and SHA256.fullmatch(row["row_identity"])
             and row["row_identity"] == canonical_identity(row),
             "routing admission row identity mismatch")

    route = row["route"]
    _require(isinstance(route, dict) and set(route) == {"source", "destination"},
             "routing admission route field set mismatch")
    _component(route["source"], "routing source")
    _component(route["destination"], "routing destination")
    _require(row["edge_id"] == canonical_edge_id(route),
             "routing admission edge_id does not bind the exact route")

    encoding = row["encoding"]
    _require(isinstance(encoding, dict)
             and set(encoding) == {
                 "owner_tile", "owner_x", "owner_y", "cfg",
                 "set_selectors", "clear_selectors", "owned_selectors",
             },
             "routing admission encoding field set mismatch")
    _require(isinstance(encoding["owner_tile"], str) and encoding["owner_tile"],
             "routing admission owner tile is invalid")
    _require(isinstance(encoding["owner_x"], int) and encoding["owner_x"] >= 0
             and isinstance(encoding["owner_y"], int) and encoding["owner_y"] >= 0,
             "routing admission owner coordinate is invalid")
    _require(isinstance(encoding["cfg"], str) and CFG.fullmatch(encoding["cfg"]),
             "routing admission owner cfg is invalid")
    for name in ("set_selectors", "clear_selectors", "owned_selectors"):
        selectors = encoding[name]
        _require(isinstance(selectors, list)
                 and len(selectors) == len(set(selectors))
                 and all(isinstance(item, int) and 0 <= item <= 4095 for item in selectors),
                 "routing admission %s are invalid" % name)
    set_selectors = set(encoding["set_selectors"])
    clear_selectors = set(encoding["clear_selectors"])
    _require(set_selectors and not set_selectors.intersection(clear_selectors)
             and set(encoding["owned_selectors"]) == set_selectors | clear_selectors,
             "routing admission selector ownership is incomplete or contradictory")

    _require(row["registry_maturity"] == "experimental",
             "routing admission maturity must be experimental")
    _require(row["evidence_tier"] == "differentially_validated",
             "routing admission evidence must be differentially_validated")
    _require(row["claim_domain"] == "exact differential routing-selector encoding",
             "routing admission claim domain mismatch")
    _require(row["strict_permission"] == "experimental-strict",
             "routing admission strict permission mismatch")
    _require(row["conflict_count"] == 0 and row["unknown_count"] == 0
             and row["terminal_edge_overlap_count"] == 0,
             "routing admission retains conflict, unknown, or terminal overlap")

    scope = row["scope"]
    _require(isinstance(scope, dict)
             and set(scope) == {"device", "package", "coordinates", "composition"},
             "routing admission scope field set mismatch")
    _require(scope["device"] == "AGRV2KL48" and scope["package"] == "L48",
             "routing admission scope must remain AGRV2KL48/L48")
    _require(scope["coordinates"] == "exact-route-and-owner-coordinates"
             and scope["composition"] == "exact-edge-only",
             "routing admission scope is broader than the exact edge")

    evidence_refs = row["evidence_refs"]
    _require(isinstance(evidence_refs, list) and evidence_refs,
             "routing admission evidence references are missing")
    for index, reference in enumerate(evidence_refs):
        _reference(reference, "routing evidence_refs[%d]" % index)
    negatives = row["retained_negative_refs"]
    _require(isinstance(negatives, list),
             "routing retained-negative references are invalid")
    for index, reference in enumerate(negatives):
        _reference(reference, "routing retained_negative_refs[%d]" % index)

    approval = row["approval"]
    _require(isinstance(approval, dict) and set(approval) == {
        "state", "approved_by", "review_date", "source_admission",
        "dossier", "dossier_identity", "admission_review",
    }, "routing admission approval field set mismatch")
    _require(approval["state"] == "approved"
             and approval["approved_by"] == "Brian Benchoff",
             "routing admission has no explicit approval")
    try:
        review_date = date.fromisoformat(approval["review_date"])
    except (TypeError, ValueError) as exc:
        raise RoutingAdmissionError("routing admission review date is invalid") from exc
    _require(review_date <= date.today(), "routing admission review date is in the future")
    _reference(approval["source_admission"], "routing source admission")
    _reference(approval["dossier"], "routing dossier")
    _reference(approval["admission_review"], "routing admission review")
    _require(isinstance(approval["dossier_identity"], str)
             and SHA256.fullmatch(approval["dossier_identity"]),
             "routing admission dossier identity is invalid")


def validate_manifest(value):
    fields = {
        "schema", "policy_version", "permission", "accounting", "rows",
        "non_claim", "scope", "provenance",
    }
    _require(isinstance(value, dict) and set(value) == fields,
             "routing admission manifest field set mismatch")
    _require(value["schema"] == SCHEMA, "unsupported routing admission schema")
    _require(value["policy_version"] == POLICY_VERSION,
             "routing admission policy version mismatch")
    _require(value["permission"] == {
        "allowed": "experimental-strict",
        "default_selection": "denied",
        "release_strict": "denied",
    }, "routing admission permission boundary mismatch")
    _require(value["scope"] == {"device": "AGRV2KL48", "package": "L48"},
             "routing admission top-level scope mismatch")
    provenance = value["provenance"]
    _require(isinstance(provenance, dict)
             and set(provenance) == {"state", "source_admission_manifest_sha256"},
             "routing admission provenance field set mismatch")
    _require(isinstance(value["non_claim"], str) and value["non_claim"],
             "routing admission non-claim is missing")
    rows = value["rows"]
    _require(isinstance(rows, list), "routing admission rows must be a list")
    _require(value["accounting"] == {"admitted_rows": len(rows)},
             "routing admission accounting mismatch")
    if rows:
        _require(provenance["state"] == "reviewed-import"
                 and isinstance(provenance["source_admission_manifest_sha256"], str)
                 and SHA256.fullmatch(provenance["source_admission_manifest_sha256"]),
                 "non-empty routing admission lacks reviewed source provenance")
    else:
        _require(provenance == {
            "state": "bootstrap-empty", "source_admission_manifest_sha256": None,
        }, "empty routing admission provenance mismatch")
    for row in rows:
        _validate_row(row)
        _require(row["approval"]["source_admission"]["sha256"]
                 == provenance["source_admission_manifest_sha256"],
                 "row source admission does not bind top-level provenance")
    edges = [row["edge_id"] for row in rows]
    routes = [route_key(row) for row in rows]
    identities = [row["row_identity"] for row in rows]
    _require(len(identities) == len(set(identities))
             and len(edges) == len(set(edges))
             and len(routes) == len(set(routes)),
             "routing admission contains duplicate identity or route keys")
    return tuple(rows)


def load_manifest(chipdb_root):
    path = Path(chipdb_root) / FILENAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingAdmissionError("missing or invalid routing admission manifest") from exc
    rows = validate_manifest(value)
    _verify_authorities(chipdb_root, rows)
    return rows


def _verify_authorities(chipdb_root, rows):
    for row in rows:
        for index, reference in enumerate(row["evidence_refs"]):
            _verify_reference(
                chipdb_root, reference, "routing evidence_refs[%d]" % index
            )
        for index, reference in enumerate(row["retained_negative_refs"]):
            _verify_reference(
                chipdb_root, reference,
                "routing retained_negative_refs[%d]" % index,
            )
        approval = row["approval"]
        _verify_reference(chipdb_root, approval["source_admission"],
                          "routing source admission")
        dossier_path = _verify_reference(
            chipdb_root, approval["dossier"], "routing dossier"
        )
        try:
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoutingAdmissionError("routing dossier is invalid JSON") from exc
        _require(canonical_dossier_identity(dossier) == approval["dossier_identity"],
                 "routing dossier identity mismatch")
        review_path = _verify_reference(
            chipdb_root, approval["admission_review"], "routing admission review"
        )
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoutingAdmissionError("routing admission review is invalid JSON") from exc
        expected = {
            "schema": "agamemnon.routing-selector-admission-approval.v1",
            "decision": "approve-experimental-routing-selector",
            "edge_id": row["edge_id"],
            "route": row["route"],
            "encoding": row["encoding"],
            "evidence_tier": row["evidence_tier"],
            "registry_maturity": row["registry_maturity"],
            "strict_permission": row["strict_permission"],
            "approved_by": approval["approved_by"],
            "review_date": approval["review_date"],
            "source_admission": approval["source_admission"],
            "dossier": approval["dossier"],
            "dossier_identity": approval["dossier_identity"],
        }
        _require(review == expected,
                 "routing admission review does not bind the exact row authority")


def manifest_identity(chipdb_root):
    path = Path(chipdb_root) / FILENAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingAdmissionError("missing or invalid routing admission manifest") from exc
    validate_manifest(value)
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def selected_rows(options, chipdb_root):
    if not options.enabled("AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT"):
        return ()
    explicit = {
        item.strip() for item in options.raw("AGAMEMNON_EXPERIMENTAL_FEATURES").split(",")
        if item.strip()
    }
    _require(options.raw("AGAMEMNON_STRICT_POLICY") == "experimental-strict",
             "routing selectors require experimental-strict policy")
    _require(OPTION_NAME in explicit or "option:" + OPTION_NAME in explicit,
             "routing selector experiment requires its explicit feature ID")
    _require(options.raw("AGAMEMNON_DEVICE") == "AGRV2KL48",
             "routing selector admission is scoped to AGRV2KL48/L48")
    incompatible = [
        name for name in (
            "AGAMEMNON_TRUE_TOPO", "AGAMEMNON_NO_INTRA_RMUX",
            "AGAMEMNON_OBS_IMUX", "AGAMEMNON_NO_EXIT_WL",
            "AGAMEMNON_BRAM_APPROACH", "AGAMEMNON_BRAM_PORTB_MCU_EXIT",
            "AGAMEMNON_BRAM_PORTB_EXIT",
        )
        if options.enabled(name)
    ]
    _require(not incompatible,
             "routing selector experiment is incompatible with graph modifier(s): %s"
             % ", ".join(incompatible))
    _require(not options.raw("AGAMEMNON_EDGE_BLACKLIST"),
             "routing selector experiment rejects a dynamic edge blacklist")
    rows = load_manifest(chipdb_root)
    if rows:
        topology = _topology_keys(chipdb_root)
        absent = [
            row["edge_id"] for row in rows
            if topology_identity(row) not in topology
        ]
        _require(not absent,
                 "routing selector admission requires observed RRG topology; absent edge(s): %s"
                 % ", ".join(absent))
        _validate_tile_and_cell_bindings(chipdb_root, rows)
        _validate_active_static_filters(chipdb_root, rows)
    return rows


def selected_edge_map(options, chipdb_root):
    """Return the one normalized mapping consumed by architecture and bitgen."""
    return {route_key(row): row for row in selected_rows(options, chipdb_root)}


def selected_binding(options, chipdb_root, rows=None):
    if not options.enabled("AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT"):
        return None
    rows = selected_rows(options, chipdb_root) if rows is None else tuple(rows)
    return {
        "routing_selector_admission_sha256": manifest_identity(chipdb_root),
        "routing_selector_row_identities": [row["row_identity"] for row in rows],
    }


def route_key(row):
    source = row["route"]["source"]
    destination = row["route"]["destination"]
    return (
        destination["x"], destination["y"], destination["family"], destination["index"],
        source["family"], source["x"], source["y"], source["index"],
    )


def topology_identity(row):
    source = row["route"]["source"]
    destination = row["route"]["destination"]
    return (
        source["tile"], source["x"], source["y"], source["family"], source["index"],
        destination["tile"], destination["x"], destination["y"],
        destination["family"], destination["index"],
    )


def _topology_keys(chipdb_root):
    keys = set()
    resource = re.compile(r"^([A-Za-z][A-Za-z0-9_]*?)(\d+)$")
    path = Path(chipdb_root) / "rrg_edges_full.csv"
    if not path.is_file():
        return frozenset()
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("source") != "observed":
                continue
            source = resource.fullmatch(row.get("src_res", ""))
            destination = resource.fullmatch(row.get("dst_res", ""))
            if source is None or destination is None:
                continue
            keys.add((
                row["src_tile"], int(row["src_x"]), int(row["src_y"]),
                source.group(1), int(source.group(2)),
                row["dst_tile"], int(row["dst_x"]), int(row["dst_y"]),
                destination.group(1), int(destination.group(2)),
            ))
    return frozenset(keys)


def _validate_tile_and_cell_bindings(chipdb_root, rows):
    tile_types = {}
    wire_resources = set()
    wires = Path(chipdb_root) / "wires.csv"
    _require(wires.is_file(), "routing admission cannot validate tile identities")
    with wires.open(newline="", encoding="utf-8") as stream:
        for item in csv.DictReader(stream):
            key = (int(item["x"]), int(item["y"]))
            prior = tile_types.setdefault(key, item["tile"])
            _require(prior == item["tile"], "chipdb coordinate has conflicting tile types")
            wire_resources.add((key[0], key[1], item["resource"]))

    cells = set()
    pips = Path(chipdb_root) / "pips_full.csv"
    _require(pips.is_file(), "routing admission cannot validate owner cells")
    with pips.open(newline="", encoding="utf-8") as stream:
        for item in csv.DictReader(stream):
            cells.add((int(item["x"]), int(item["y"]), item["mux"], int(item["sel"])))

    for row in rows:
        source = row["route"]["source"]
        destination = row["route"]["destination"]
        _require(source["tile"] == "LogicTILE" and destination["tile"] == "LogicTILE",
                 "experimental routing rows are limited to LogicTILE observed topology")
        _require(source["family"] == "RMUX" and destination["family"] == "RMUX",
                 "experimental routing rows are limited to the general RMUX mesh")
        for component, label in ((source, "source"), (destination, "destination")):
            _require(tile_types.get((component["x"], component["y"])) == component["tile"],
                     "routing %s tile identity mismatch" % label)
            _require((component["x"], component["y"], _resource(component))
                     in wire_resources,
                     "routing %s wire identity mismatch" % label)
        encoding = row["encoding"]
        _require(tile_types.get((encoding["owner_x"], encoding["owner_y"]))
                 == encoding["owner_tile"],
                 "routing encoding owner tile identity mismatch")
        missing = [
            entry for entry in emission_entries(row) + clearing_entries(row)
            if entry not in cells
        ]
        _require(not missing, "routing encoding owner cell(s) missing: %s" % missing)


def _resource(component):
    return "%s%02d" % (component["family"], component["index"])


def _edge_nodes(row):
    source = row["route"]["source"]
    destination = row["route"]["destination"]
    return (
        (_resource(source), str(source["x"]), str(source["y"])),
        (_resource(destination), str(destination["x"]), str(destination["y"])),
    )


def _validate_active_static_filters(chipdb_root, rows):
    """Require every admitted observed row to survive the default static graph filters."""
    root = Path(chipdb_root)
    dead = set()
    dead_path = root / "dead_edges_silicon.csv"
    if dead_path.is_file():
        pattern = re.compile(
            r"([A-Za-z][A-Za-z0-9_]*\d+)@(-?\d+),(-?\d+)\s*->\s*"
            r"([A-Za-z][A-Za-z0-9_]*\d+)@(-?\d+),(-?\d+)"
        )
        with dead_path.open(newline="", encoding="utf-8") as stream:
            for item in csv.DictReader(stream):
                match = pattern.fullmatch(item.get("edge", "").strip())
                _require(match is not None, "malformed silicon-dead edge")
                dead.add((match.group(1), match.group(2), match.group(3),
                          match.group(4), match.group(5), match.group(6)))

    exit_allowed = {}
    exit_path = root / "exit_feeder_whitelist.csv"
    if exit_path.is_file():
        with exit_path.open(newline="", encoding="utf-8") as stream:
            for item in csv.DictReader(stream):
                destination = (item["dst_res"], item["dst_x"], item["dst_y"])
                source = (item["src_res"], item["src_x"], item["src_y"])
                exit_allowed.setdefault(destination, set()).add(source)

    corridor_destinations = set()
    corridor_sources = set()
    corridor_allowed = set()
    corridor_path = root / "bram_portb_corridors.csv"
    if corridor_path.is_file():
        with corridor_path.open(newline="", encoding="utf-8") as stream:
            for item in csv.DictReader(stream):
                source = (item["src_res"], item["src_x"], item["src_y"])
                destination = (item["dst_res"], item["dst_x"], item["dst_y"])
                corridor_allowed.add(source + destination)
                if item["port"] == "AddressB":
                    corridor_destinations.add(destination)
                if item["port"] == "DataOutB":
                    corridor_sources.add(source)

    for row in rows:
        source, destination = _edge_nodes(row)
        edge = source + destination
        _require(edge not in dead,
                 "routing selector admission contains a silicon-dead edge")
        _require(destination not in exit_allowed or source in exit_allowed[destination],
                 "routing selector admission is pruned by the exit-feeder whitelist")
        _require((destination not in corridor_destinations
                  and source not in corridor_sources) or edge in corridor_allowed,
                 "routing selector admission is pruned by the BRAM corridor")
        _require(destination[1:] != ("13", "4"),
                 "routing selector admission cannot target the BRAM boundary")


def emission_entries(row):
    encoding = row["encoding"]
    return tuple(
        (encoding["owner_x"], encoding["owner_y"], encoding["cfg"], selector)
        for selector in encoding["set_selectors"]
    )


def clearing_entries(row):
    encoding = row["encoding"]
    return tuple(
        (encoding["owner_x"], encoding["owner_y"], encoding["cfg"], selector)
        for selector in encoding["clear_selectors"]
    )


def claim_metadata(row):
    approval = row["approval"]
    return ClaimMetadata(
        evidence_tier=row["evidence_tier"],
        claim_domain=row["claim_domain"],
        claim_scope="AGRV2KL48/L48 exact route and owner coordinates; exact edge only",
        policy_version=POLICY_VERSION,
        approval_state=approval["state"],
        approved_by=approval["approved_by"],
        review_date=approval["review_date"],
        individual_only=False,
        emits=True,
        evidence_refs=tuple(row["evidence_refs"]),
        retained_negative_refs=tuple(row["retained_negative_refs"]),
        conflict_count=row["conflict_count"],
        unknown_count=row["unknown_count"],
        negative_conflict=False,
    )
