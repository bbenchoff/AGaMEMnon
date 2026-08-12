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

# D0 default-promotion amendment gate.  The amendment enlarges the default "can
# build" set to witnessed, differentially-validated routing rows, but only once
# the owner records the separate hash-approval artifact below.  When the artifact
# is ABSENT the gate is UN-approved and nothing is promoted -- live behavior is
# unchanged.  The artifact is deliberately not shipped; its presence + validity
# is what flips the default (see :func:`default_promotion_populations`).
DEFAULT_PROMOTION_FILENAME = "d0_default_promotion_approval.json"
DEFAULT_PROMOTION_SCHEMA = "agamemnon.d0-default-promotion-amendment-approval.v1"
DEFAULT_PROMOTION_DECISION = "promote-witnessed-differential-routing-to-default"


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


_GRAPH_MODIFIERS = (
    "AGAMEMNON_TRUE_TOPO", "AGAMEMNON_NO_INTRA_RMUX", "AGAMEMNON_OBS_IMUX",
    "AGAMEMNON_NO_EXIT_WL", "AGAMEMNON_BRAM_APPROACH",
    "AGAMEMNON_BRAM_PORTB_MCU_EXIT", "AGAMEMNON_BRAM_PORTB_EXIT",
)


def _reject_graph_modifiers(options):
    incompatible = [name for name in _GRAPH_MODIFIERS if options.enabled(name)]
    _require(not incompatible,
             "routing selector experiment is incompatible with graph modifier(s): %s"
             % ", ".join(incompatible))
    _require(not options.raw("AGAMEMNON_EDGE_BLACKLIST"),
             "routing selector experiment rejects a dynamic edge blacklist")


def _validate_selected(chipdb_root, rows):
    """Apply the shared fail-closed graph checks to any admitted row set."""
    if not rows:
        return
    _validate_tile_and_cell_bindings(chipdb_root, rows)
    topology = _topology_keys(chipdb_root)
    absent = [
        row["edge_id"] for row in rows
        if topology_identity(row) not in topology
        and not supplies_architecture_pip(row)
    ]
    _require(not absent,
             "routing selector admission requires observed RRG topology; absent edge(s): %s"
             % ", ".join(absent))
    _validate_active_static_filters(chipdb_root, rows)


def _validate_default_promotion_approval(value, chipdb_root):
    """Fail closed unless the amendment approval binds the exact reviewed bytes."""
    fields = {
        "schema", "decision", "state", "approved_by", "review_date",
        "policy_version", "routing_selector_admission_sha256",
        "promoted_population_dossier_identities", "scope",
    }
    _require(isinstance(value, dict) and set(value) == fields,
             "D0 default-promotion approval field set mismatch")
    _require(value["schema"] == DEFAULT_PROMOTION_SCHEMA,
             "unsupported D0 default-promotion approval schema")
    _require(value["decision"] == DEFAULT_PROMOTION_DECISION,
             "D0 default-promotion approval decision mismatch")
    _require(value["state"] == "approved" and value["approved_by"] == "Brian Benchoff",
             "D0 default-promotion approval has no explicit owner approval")
    _require(value["policy_version"] == POLICY_VERSION,
             "D0 default-promotion approval policy version mismatch")
    try:
        review_date = date.fromisoformat(value["review_date"])
    except (TypeError, ValueError) as exc:
        raise RoutingAdmissionError(
            "D0 default-promotion approval review date is invalid"
        ) from exc
    _require(review_date <= date.today(),
             "D0 default-promotion approval review date is in the future")
    _require(value["scope"] == {
        "device": "AGRV2KL48", "package": "L48", "claim": "routing-selection-only",
    }, "D0 default-promotion approval scope must remain L48 routing-selection-only")
    declared = value["routing_selector_admission_sha256"]
    _require(isinstance(declared, str) and SHA256.fullmatch(declared),
             "D0 default-promotion approval admission hash is invalid")
    _require(declared == manifest_identity(chipdb_root),
             "D0 default-promotion approval does not bind the exact reviewed population")
    promoted = value["promoted_population_dossier_identities"]
    _require(isinstance(promoted, list) and promoted
             and len(promoted) == len(set(promoted))
             and all(isinstance(item, str) and SHA256.fullmatch(item) for item in promoted),
             "D0 default-promotion approval promoted populations are invalid")
    available = {row["approval"]["dossier_identity"] for row in load_manifest(chipdb_root)}
    unknown = [item for item in promoted if item not in available]
    _require(not unknown,
             "D0 default-promotion approval promotes populations absent from the reviewed "
             "admission: %s" % ", ".join(unknown))


def default_promotion_populations(chipdb_root):
    """Return the approved population wave-dossier identities this amendment promotes.

    The amendment approval artifact is the separate hash gate the directive
    requires.  When it is absent the gate is UN-approved and nothing is promoted
    (live behavior unchanged).  When it is present it must bind the exact reviewed
    routing-selector admission bytes and only populations that actually exist in
    that admission, or the build fails closed.  Only witnessed, reviewed
    populations can ever appear here: predicted/decoded/unwitnessed material has
    no dossier in the admission and can never be listed.
    """
    path = Path(chipdb_root) / DEFAULT_PROMOTION_FILENAME
    if not path.is_file():
        return frozenset()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingAdmissionError(
            "invalid D0 default-promotion approval artifact"
        ) from exc
    _validate_default_promotion_approval(value, chipdb_root)
    return frozenset(value["promoted_population_dossier_identities"])


def _experiment_rows(options, chipdb_root):
    """The unchanged opt-in experimental-strict selection surface."""
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
    _reject_graph_modifiers(options)
    return load_manifest(chipdb_root)


def _default_promotion_rows(options, chipdb_root):
    """Amendment-gated default-graph rows: witnessed routing only, no opt-in flag.

    This path activates only under the default release-strict policy, only on the
    qualified L48 package, only when the amendment approval gate promotes the
    row's population wave-dossier, and only for witnessed-routing rows that supply
    an exact architecture pip.  Every remaining fail-closed check (authority,
    topology, cell bindings, static negatives) still runs through
    :func:`_validate_selected`.  Predicted/unwitnessed rows are excluded twice:
    they carry no promoted dossier and they are not architecture-pip suppliers.
    """
    if options.raw("AGAMEMNON_STRICT_POLICY") != "release-strict":
        return ()
    if options.raw("AGAMEMNON_DEVICE") != "AGRV2KL48":
        return ()
    promoted = default_promotion_populations(chipdb_root)
    if not promoted:
        return ()
    _reject_graph_modifiers(options)
    return tuple(
        row for row in load_manifest(chipdb_root)
        if supplies_architecture_pip(row)
        and row["approval"]["dossier_identity"] in promoted
    )


def selected_rows(options, chipdb_root):
    if options.enabled("AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT"):
        rows = _experiment_rows(options, chipdb_root)
    else:
        rows = _default_promotion_rows(options, chipdb_root)
    _validate_selected(chipdb_root, rows)
    return rows


def selected_edge_map(options, chipdb_root):
    """Return the one normalized mapping consumed by architecture and bitgen."""
    return {route_key(row): row for row in selected_rows(options, chipdb_root)}


def selected_binding(options, chipdb_root, rows=None):
    rows = selected_rows(options, chipdb_root) if rows is None else tuple(rows)
    if not rows:
        return None
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


def _is_l48_rmux30_destination(row):
    """Recognize only the named executable perimeter class in the R5 freeze."""
    source = row["route"]["source"]
    destination = row["route"]["destination"]
    encoding = row["encoding"]
    return (
        source["tile"] == "LogicTILE" and source["family"] == "RMUX"
        and destination["tile"] == "IOTILE"
        and destination["x"] == 0 and destination["y"] in (2, 4)
        and destination["family"] == "RMUX" and destination["index"] == 30
        and encoding["owner_tile"] == "IOTILE"
        and encoding["owner_x"] == destination["x"]
        and encoding["owner_y"] == destination["y"]
    )


def supplies_architecture_pip(row):
    """Whether one exact approved row may supply its otherwise-absent graph pip.

    This is deliberately not a geometric pad-feed rule.  It recognizes only an
    individually admitted LogicTILE RMUX -> IOTILE RMUX row whose selector field
    is owned by that exact destination IOTILE.  The caller still has to obtain
    the row through :func:`selected_rows`, including the experimental triple
    gate and all authority, endpoint, cell, and static-negative checks.
    """
    encoding = row["encoding"]
    return (
        _is_l48_rmux30_destination(row)
        and encoding["cfg"] == "CFG_RMUX3"
        and set(encoding["owned_selectors"]).issubset(range(40, 50))
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
        logic_mesh = (
            source["tile"] == destination["tile"] == "LogicTILE"
            and source["family"] == destination["family"] == "RMUX"
        )
        iotile_destination = _is_l48_rmux30_destination(row)
        _require(logic_mesh or iotile_destination,
                 "experimental routing rows must be exact LogicTILE RMUX mesh "
                 "or LogicTILE-to-IOTILE RMUX rows")
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
        if iotile_destination:
            _require(encoding["cfg"] == "CFG_RMUX3",
                     "IOTILE routing encoding owner group mismatch")
            _require(set(encoding["owned_selectors"]).issubset(range(40, 50)),
                     "IOTILE routing encoding escapes the destination selector field")
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
