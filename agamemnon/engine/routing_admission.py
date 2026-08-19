"""Fail-closed contract for row-tiered experimental routing selectors.

The release selector database is admitted as one individually-qualified
surface and must never receive differential-only rows.  This module defines a
separate exact-row format and resolves explicit experimental selections for
both architecture construction and bitstream emission.
"""

from __future__ import annotations

import contextvars
import csv
import hashlib
import json
import re
import tempfile
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
    # The file form is the same dynamic blacklist with a bigger container, so it
    # has to be rejected here too -- otherwise the guard is trivially bypassed by
    # moving the edges into a file.
    _require(not options.raw("AGAMEMNON_EDGE_BLACKLIST_FILE"),
             "routing selector experiment rejects a dynamic edge blacklist file")


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


# --------------------------------------------------------------------------- #
# D0 subordination rules (2026-08-17 approval; see
# tools/agamemnon/wave_factory/D0_SUBORDINATION_PROPOSAL.md in AG32-Docs and
# D0_SUBORDINATION_APPROVAL_2026-08-17.json).  Both rules below are mandatory,
# fail-closed preconditions of a valid D0 default-promotion approval artifact --
# neither is reachable through any option/env var, and neither substitutes for
# the other or for the existing human sign-offs.  They exist to make the
# 2026-08-11 byte-72544 collision (a promoted row and the shipped physical_io
# left-edge companion field both writing IOTILE(0,4) CFG_RMUX3 selector 45)
# structurally impossible to approve, and to make any promoted pip that would
# change a retained qualified route's emitted bitstream structurally impossible
# to approve as well.
# --------------------------------------------------------------------------- #


def _pip_byte_map(chipdb_root):
    """(x, y, mux, sel) -> (byte, mask) for every CFG_RMUX/CFG_IMUX mesh cell.

    This is exactly the domain a routing-selector-admission row's ``encoding``
    can ever name (see ``_validate_tile_and_cell_bindings``), so it is the
    correct, and sufficient, resolver for the candidate promotion's own owned
    selector cells.
    """
    result = {}
    path = Path(chipdb_root) / "pips_full.csv"
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            result[(int(row["x"]), int(row["y"]), row["mux"], int(row["sel"]))] = (
                int(row["byte"]), int(row["mask"]),
            )
    return result


def _io_selector_cell_map(chipdb_root):
    """(x, y, mux, sel) -> (byte, mask) across the mesh AND package-IO domains.

    physical_io's left-edge corridor and companion fields reference both
    CFG_RMUX/CFG_IMUX mesh selectors (``pips_full.csv``) and CFG_IOMUX-family
    package-IO selectors (``pips_io.csv``, ``kind=mux`` rows) -- disjoint
    tables sharing the same (x, y, mux, sel, byte, mask) schema.
    """
    result = _pip_byte_map(chipdb_root)
    path = Path(chipdb_root) / "pips_io.csv"
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                result[(int(row["x"]), int(row["y"]), row["mux"], int(row["sel"]))] = (
                    int(row["byte"]), int(row["mask"]),
                )
    return result


def _expand_bits(entries):
    """{(byte, mask), ...} -> {(byte, bit_index), ...} for exact bit comparison.

    Two (byte, mask) declarations with different mask VALUES can still share a
    bit (e.g. mask 0x03 and mask 0x02); comparing declared masks directly would
    miss that overlap, so every comparison in this module happens at the
    single-bit level instead.
    """
    bits = set()
    for byte, mask in entries:
        for bit in range(8):
            if mask & (1 << bit):
                bits.add((byte, bit))
    return bits


def _read_direct_byte_rows(path, byte_field, mask_field):
    """Rows whose byte/mask are literal integer columns (one cell per row)."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            result.add((int(row[byte_field]), int(row[mask_field])))
    return result


def _read_codeword_rows(path, byte_field, mask_field):
    """Rows whose byte/mask are comma-separated parallel lists (pad-feed codewords)."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            bytes_ = [int(item) for item in (row.get(byte_field) or "").split(",") if item]
            masks = [int(item) for item in (row.get(mask_field) or "").split(",") if item]
            if len(bytes_) != len(masks):
                raise RoutingAdmissionError(
                    "%s: malformed codeword row for the D0 disjointness scan" % path.name
                )
            result.update(zip(bytes_, masks))
    return result


def _read_bit_rows(path, byte_field, bit_field):
    """Rows naming a byte plus a single bit index (measured electrical fields)."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            result.add((int(row[byte_field]), 1 << int(row[bit_field])))
    return result


def _read_pad_input_bytes(path):
    """pad_input_L48.csv: either a direct enable byte/mask, or explicit
    semicolon ``byte:mask`` set/clear cell lists (``-`` means deliberately none)."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            try:
                enable_byte, enable_mask = int(row["enable_byte"]), int(row["enable_mask"])
            except (KeyError, ValueError):
                enable_byte = enable_mask = 0
            if enable_byte or enable_mask:
                result.add((enable_byte, enable_mask))
            for field in ("set_cells", "clear_cells"):
                text = (row.get(field) or "").strip()
                if not text or text == "-":
                    continue
                for part in text.split(";"):
                    if not part:
                        continue
                    byte_text, mask_text = part.split(":")
                    result.add((int(byte_text), int(mask_text)))
    return result


def _read_vendor_cell_pairs(path):
    """iomux_hop_vendor.csv: comment-prefixed rows with explicit
    semicolon ``byte:mask`` set/clear cell lists."""
    result = set()
    if not path.is_file():
        return result
    with path.open(encoding="utf-8") as stream:
        rows = csv.DictReader(line for line in stream if not line.lstrip().startswith("#"))
        for row in rows:
            for field in ("set_cells", "clear_cells"):
                text = (row.get(field) or "").strip()
                if not text:
                    continue
                for part in text.split(";"):
                    if not part:
                        continue
                    byte_text, mask_text = part.split(":")
                    result.add((int(byte_text), int(mask_text)))
    return result


def _read_selector_group_rows(path, cell_map):
    """Rows declaring an explicit x, y, cfg_group + set/clear selector lists,
    resolved to physical bytes through the shared cell map.  Fails closed if a
    declared selector has no resolvable cell -- an unresolvable declared
    selector cannot be proven disjoint, so it cannot be treated as safe."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            cfg = (row.get("cfg_group") or "").strip()
            if not cfg:
                continue
            x, y = int(row["x"]), int(row["y"])
            selectors = set()
            for field in ("set_selectors", "clear_selectors"):
                selectors.update(
                    int(item) for item in (row.get(field) or "").split(";") if item
                )
            for selector in selectors:
                key = (x, y, cfg, selector)
                resolved = cell_map.get(key)
                if resolved is None:
                    raise RoutingAdmissionError(
                        "%s: selector %s@%d,%d sel%d has no resolvable cell for "
                        "the D0 shipped-feature disjointness scan"
                        % (path.name, cfg, x, y, selector)
                    )
                result.add(resolved)
    return result


def _read_companion_rows(path, cell_map):
    """padfeed_L48_left.csv's companion_cfg/companion_sels fixed left-edge
    fields -- exactly the mechanism behind the 2026-08-11 byte-72544 collision."""
    result = set()
    if not path.is_file():
        return result
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            cfg = (row.get("companion_cfg") or "").strip()
            if not cfg:
                continue
            x, y = int(row["padtile_x"]), int(row["padtile_y"])
            for item in (row.get("companion_sels") or "").split(","):
                item = item.strip()
                if not item:
                    continue
                key = (x, y, cfg, int(item))
                resolved = cell_map.get(key)
                if resolved is None:
                    raise RoutingAdmissionError(
                        "%s: companion selector %s@%d,%d sel%s has no resolvable "
                        "cell for the D0 shipped-feature disjointness scan"
                        % (path.name, cfg, x, y, item)
                    )
                result.add(resolved)
    return result


# The fixed GPIO5 L48 inactive-terminal default cells mcu_gpio ("mcu_edge")
# always selects whenever a design uses the GPIO5 hard-boundary corridor -- see
# features/mcu_gpio.py: McuGpioFeature.prepare.  Kept here as an explicit,
# independently-checked constant (rather than calling the real feature, which
# fails closed via SystemExit against a chipdb with no GPIO5 wiring at all --
# exactly the synthetic chipdbs the D0 mechanism's own tests build) so this
# scan degrades to "nothing declared" instead of aborting when a chipdb simply
# has no mcu_gpio table.  test_mcu_gpio_owned_bytes_matches_the_real_feature
# pins this constant against the live feature code so it cannot silently drift.
_MCU_GPIO5_INACTIVE_TERMINAL_CELLS = tuple(
    (9, 5, "BBMUXS%d" % mux, 8) for mux in (0, 1, 3, 4, 5, 6, 7)
)


def _mcu_gpio_owned_bytes(chipdb_root):
    path = Path(chipdb_root) / "pips_mcuedge.csv"
    if not path.is_file():
        return set()
    cell_map = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            cell_map[(int(row["x"]), int(row["y"]), row["mux"], int(row["sel_index"]))] = (
                int(row["byte"]), int(row["mask"]),
            )
    return {
        cell_map[key] for key in _MCU_GPIO5_INACTIVE_TERMINAL_CELLS if key in cell_map
    }


def _shipped_feature_owned_bytes(chipdb_root):
    """The statically declared byte footprint of every individually-qualified,
    package-facing shipped feature a routing-selector row could plausibly
    collide with: physical_io (package pad output/input), mcu_gpio ("mcu_edge",
    the MCU/fabric GPIO5 hard-boundary corridor), bram, and PLL/HSE (via
    clocks' HSE input-enable and BRAM's shared pips_bram_pll.csv cell map).

    General infrastructure features (routing, core_logic, carry, route_through)
    are deliberately excluded: their own declared writable_regions span
    ``pips_full.csv`` in its entirety (they are the generic resolvers every
    routed design's pips flow through), so including them would make every
    candidate collide by construction and defeat the purpose of this rule.
    Hard MCU peripherals (UART/SPI/I2C) have no fabric bitstream footprint at
    all and so contribute nothing here.  ``mcu_ahb`` (the External-AHB
    register-bank corridor feature, also "MCU_EDGES" phase) is likewise
    excluded: every candidate routing-selector row is, by construction,
    confined to CFG_RMUX/CFG_IMUX mesh cells or the IOTILE(0, y) CFG_RMUX3
    class (see ``supplies_architecture_pip`` and ``_validate_tile_and_cell_
    bindings``), while mcu_ahb's corridor selectors resolve through a
    disjoint MCU-edge cell table (InputMUX/BBMUXE-family) at disjoint tile
    coordinates -- there is no plausible collision surface between the two,
    and mcu_ahb's mixed exact/corridor cell-table resolution mechanism is not
    the one this scan's helpers implement.

    Every reader below degrades to "nothing declared" when its source file is
    absent (the common case for a synthetic/partial chipdb), but fails closed
    with :class:`RoutingAdmissionError` if a file IS present and references a
    selector this scan cannot resolve to a physical cell -- an unresolvable
    reference can never be proven disjoint.
    """
    root = Path(chipdb_root)
    io_cells = _io_selector_cell_map(root)
    owned = set()

    # physical_io
    owned |= _read_direct_byte_rows(root / "pips_io.csv", "byte", "mask")
    owned |= _read_codeword_rows(root / "padfeed_L48_top.csv", "codeword_bytes", "codeword_masks")
    owned |= _read_codeword_rows(root / "padfeed_L48_left.csv", "codeword_bytes", "codeword_masks")
    owned |= _read_companion_rows(root / "padfeed_L48_left.csv", io_cells)
    owned |= _read_pad_input_bytes(root / "pad_input_L48.csv")
    owned |= _read_bit_rows(root / "io_pad_electrical_L48.csv", "raw_byte", "bit")
    owned |= _read_selector_group_rows(root / "pad_oe_L48_left_corridors.csv", io_cells)
    owned |= _read_selector_group_rows(root / "pad_input_L48_left_corridors.csv", io_cells)
    owned |= _read_vendor_cell_pairs(root / "iomux_hop_vendor.csv")

    # bram (and the shared BRAM/PLL cell map)
    for filename in (
        "bram_cell.csv", "bram_rom_ctrl.csv", "bram_dual_ctrl.csv",
        "bram_portb_read_ctrl.csv", "bram_portb_const_ctrl.csv", "bram_pip_cfg.csv",
    ):
        owned |= _read_direct_byte_rows(root / filename, "byte", "mask")
    # bram.py's own writable_regions declare this path relative to the engine
    # package directory (one level up from chipdb), not the chipdb root.
    owned |= _read_direct_byte_rows(root.parent / "engine" / "pips_bram_pll.csv", "byte", "mask")

    # mcu_gpio ("mcu_edge")
    owned |= _mcu_gpio_owned_bytes(root)

    return owned


def _candidate_promoted_bit_claims(rows, promoted, cell_map):
    """{(byte, bit): {dossier_identity, ...}} for every bit the candidate
    promotion (the union of every row whose population is in ``promoted``)
    would write.  Fails closed if an owned selector has no resolvable cell."""
    claims = {}
    for row in rows:
        dossier = row["approval"]["dossier_identity"]
        if dossier not in promoted:
            continue
        encoding = row["encoding"]
        for selector in encoding["owned_selectors"]:
            key = (encoding["owner_x"], encoding["owner_y"], encoding["cfg"], selector)
            resolved = cell_map.get(key)
            if resolved is None:
                raise RoutingAdmissionError(
                    "D0 default-promotion approval owns an unresolvable selector "
                    "cell: %s@%d,%d sel%d" % (encoding["cfg"], key[0], key[1], selector)
                )
            byte, mask = resolved
            for bit in range(8):
                if mask & (1 << bit):
                    claims.setdefault((byte, bit), set()).add(dossier)
    return claims


def _validate_disjointness(chipdb_root, rows, promoted):
    """Rule 1 (byte/selector disjointness): reject the approval artifact on ANY
    bit overlap between the candidate promotion's own owned bits, each other
    (across distinct populations promoted together), and every individually-
    qualified shipped feature's owned bits.  This is a fail-closed precondition
    of the approval artifact itself, unconditional on any option or env var."""
    cell_map = _pip_byte_map(chipdb_root)
    claims = _candidate_promoted_bit_claims(rows, promoted, cell_map)
    cross_population = sorted(
        "byte %d bit %d (%s)" % (byte, bit, ", ".join(sorted(dossiers)))
        for (byte, bit), dossiers in claims.items() if len(dossiers) > 1
    )
    _require(not cross_population,
             "D0 default-promotion approval promotes populations that collide "
             "with each other at: %s" % "; ".join(cross_population))

    try:
        shipped_bits = _expand_bits(_shipped_feature_owned_bytes(chipdb_root))
    except RoutingAdmissionError:
        raise
    except (OSError, UnicodeDecodeError, KeyError, ValueError) as exc:
        raise RoutingAdmissionError(
            "D0 default-promotion approval cannot verify shipped-feature byte "
            "disjointness: %s" % exc
        ) from exc
    overlap = sorted(
        "byte %d bit %d" % key for key in set(claims) & shipped_bits
    )
    _require(not overlap,
             "D0 default-promotion approval collides with an individually-"
             "qualified shipped feature's owned bit(s): %s" % ", ".join(overlap))


_ROUTE_INVARIANCE_GUARD = contextvars.ContextVar(
    "agamemnon_d0_route_invariance_guard", default=False
)

# default-promotion only ever activates under release-strict/AGRV2KL48 (see
# _default_promotion_rows); a retained artifact built under any other policy
# can never be affected by this gate, so rebuilding it here would prove
# nothing and only make the check slower and more fragile.
_ROUTE_INVARIANCE_IRRELEVANT_KEYS = ("AGAMEMNON_STRICT_POLICY", "AGAMEMNON_RESEARCH_UNSAFE")


def _qualified_pack_registry_path():
    """Fixed relative to the installed package -- never influenced by
    chipdb_root or any AGAMEMNON_* option, so this lookup itself cannot be
    steered by the environment a build happens to run under."""
    return Path(__file__).resolve().parents[2] / "qualification" / "pack_regression.json"


def _route_invariance_relevant_artifacts(artifacts):
    relevant = []
    for artifact in artifacts:
        environment = artifact.get("environment")
        if not isinstance(environment, dict):
            raise RoutingAdmissionError(
                "D0 route-invariance registry entry has a malformed environment: %r"
                % (artifact,)
            )
        if any(environment.get(key) for key in _ROUTE_INVARIANCE_IRRELEVANT_KEYS):
            continue
        relevant.append(artifact)
    return relevant


def _real_route_invariance_check(value, chipdb_root):
    """Rule 2 (route-invariance regression): rebuild every retained,
    release-strict-relevant qualified artifact with this candidate promotion
    active, and reject the approval artifact if any rebuilt bitstream differs
    from the retained one -- or if the rebuild cannot be completed at all.

    This is the literal implementation of "a default-promoted population must
    never alter a retained qualified image": absence of the ability to verify
    is treated exactly like a positive mismatch.  Both reject.  Unconditional
    on any option or env var, and inseparable from approval validity: it runs
    every time an approval artifact is read (:func:`default_promotion_populations`),
    not just once at write time.
    """
    if _ROUTE_INVARIANCE_GUARD.get():
        # Already inside an outer route-invariance rebuild pass: this call was
        # reached by that pass's own in-process rebuild of one retained
        # artifact against the very candidate under test.  Recursing into a
        # second full rebuild pass here would never terminate; the OUTER call
        # is the one whose verdict actually gates this approval.
        return
    registry_path = _qualified_pack_registry_path()
    if not registry_path.is_file():
        # A literally absent registry is exactly the "rebuild cannot be
        # completed at all" case the docstring above already commits to
        # rejecting -- it must not be read as "nothing was ever retained".
        # This is not hypothetical: pyproject.toml's package-data never lists
        # "qualification", so a real installed release wheel never ships
        # qualification/pack_regression.json at all, and this is the exact
        # path a real D0 default-promotion approval artifact would hit in
        # that environment. Silently returning here would let Rule 2 pass
        # vacuously for every such build instead of failing closed.
        raise RoutingAdmissionError(
            "D0 route-invariance check cannot find the retained qualified "
            "artifact registry at %s" % registry_path
        )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        artifacts = registry["artifacts"]
        if not isinstance(artifacts, list):
            raise ValueError("artifacts is not a list")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise RoutingAdmissionError(
            "D0 route-invariance check cannot load the retained qualified "
            "artifact registry: %s" % exc
        ) from exc
    repo_root = registry_path.parent.parent
    relevant = _route_invariance_relevant_artifacts(artifacts)
    token = _ROUTE_INVARIANCE_GUARD.set(True)
    try:
        from agamemnon.engine import bitgen  # local import: avoid an import cycle
        with tempfile.TemporaryDirectory(prefix="agamemnon-d0-route-invariance-") as tmp:
            for artifact in relevant:
                routed_rel = artifact.get("routed")
                expected = artifact.get("bitstream_sha256")
                environment = artifact["environment"]
                if (not isinstance(routed_rel, str) or not routed_rel
                        or not isinstance(expected, str) or not SHA256.fullmatch(expected)):
                    raise RoutingAdmissionError(
                        "D0 route-invariance registry entry is malformed: %r" % (artifact,)
                    )
                routed_path = (repo_root / routed_rel).resolve()
                try:
                    routed_path.relative_to(repo_root)
                except ValueError as exc:
                    raise RoutingAdmissionError(
                        "D0 route-invariance registry entry escapes the "
                        "repository: %s" % routed_rel
                    ) from exc
                if not routed_path.is_file():
                    raise RoutingAdmissionError(
                        "D0 route-invariance registry entry is missing: %s" % routed_rel
                    )
                output_path = Path(tmp) / (Path(routed_rel).stem + ".bin")
                environ = dict(environment)
                environ["AGAMEMNON_DATA"] = str(chipdb_root)
                try:
                    bitgen.build(str(routed_path), str(output_path), environ=environ)
                    actual = hashlib.sha256(output_path.read_bytes()).hexdigest()
                except (Exception, SystemExit) as exc:
                    raise RoutingAdmissionError(
                        "D0 route-invariance check could not rebuild retained "
                        "artifact %s with the candidate promotion active: %s"
                        % (routed_rel, exc)
                    ) from exc
                _require(
                    actual == expected,
                    "D0 route-invariance regression: candidate promotion changes "
                    "the retained qualified artifact %s (expected %s, got %s)"
                    % (routed_rel, expected, actual),
                )
    finally:
        _ROUTE_INVARIANCE_GUARD.reset(token)


def rebuild_retained_qualified_artifacts(chipdb_root):
    """Public, D0-approval-independent entry point for Rule 2's rebuild check.

    ``_real_route_invariance_check`` never actually reads its ``value``
    parameter: Rule 2 is really just "rebuild every retained, release-strict-
    relevant qualified artifact against ``chipdb_root`` and reject on any
    mismatch or on any inability to rebuild" -- a property of ``chipdb_root``
    alone, not of any particular D0 default-promotion approval artifact. This
    function names that property directly so a caller with no approval
    artifact in hand at all -- e.g. a bare hand edit to a chipdb data file,
    which never goes through :func:`default_promotion_populations` and so
    never reaches Rule 2 today -- can still run the identical check.

    This closes GAP 1 from the 2026-08-18 seven-artifact incident review
    (AG32-Docs docs/TASK_QUEUE.md queue B task B3): Rule 2 only ran when a D0
    approval artifact was read, so a plain chipdb edit committed outside that
    path was completely ungated. See ``tests/conftest.py``'s
    ``chipdb_change_gate_failure`` / the autouse ``_chipdb_change_gate``
    fixture, which is what actually calls this for every pytest session.

    Fails exactly as :func:`_real_route_invariance_check` already does --
    unconditional on any option or env var, and raising
    :class:`RoutingAdmissionError` on the first mismatch or the first
    artifact that cannot be rebuilt at all (absence of the ability to verify
    is treated exactly like a positive mismatch). This function changes
    nothing about that contract; it only removes the requirement that a D0
    approval artifact be the trigger.
    """
    _real_route_invariance_check(None, chipdb_root)


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
    rows = load_manifest(chipdb_root)
    available = {row["approval"]["dossier_identity"] for row in rows}
    unknown = [item for item in promoted if item not in available]
    _require(not unknown,
             "D0 default-promotion approval promotes populations absent from the reviewed "
             "admission: %s" % ", ".join(unknown))

    # Rule 1 -- byte/selector disjointness (mandatory; see the D0 subordination
    # rules banner above).  Fails closed before Brian, or anyone, could ever be
    # offered this artifact as a valid one to sign.
    promoted_set = set(promoted)
    _validate_disjointness(chipdb_root, rows, promoted_set)

    # Rule 2 -- route-invariance regression (mandatory; see the same banner).
    # Unconditional: there is no parameter or option that can skip this call.
    _real_route_invariance_check(value, chipdb_root)


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
