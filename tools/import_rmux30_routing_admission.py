#!/usr/bin/env python3
"""Import the exact approved R5 L48 RMUX30 population admission.

The importer is deliberately pinned to one source review and one approval
receipt.  It emits six experimental-strict rows, retains both terminal
exclusions, and refuses any pre-existing non-bootstrap public admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agamemnon.engine import routing_admission  # noqa: E402


REVIEW_SHA256 = "a5c61e0537c40bcf2e046647aa44158c240d954991ada64dfb733770390ea6c6"
REVIEW_IDENTITY = "06cb40d3552d44516576de2b7f4bc58bb41ff92f44ab3c8435513711e5a5309a"
RECEIPT_SHA256 = "84530caca717c9b519d7c4ae3d3e1c9696f135dc24d6223da809cca5521715d9"
RECEIPT_IDENTITY = "5a98aae13cf6ce08b844750c464716c51153ef922c4bb9390e4fd5785e65c4f7"
BOOTSTRAP_SHA256 = "47fd8f110b3f23ba5c0c7868bbf09477a1c76f52c34592381ac913d3b7d3b728"
REVIEW_DATE = "2026-08-09"

SOURCE_NAME = "routing_rmux30_source_approval.json"
EVIDENCE_NAME = "routing_rmux30_holdout_evidence.json"
NEGATIVE_NAME = "routing_rmux30_terminal_exclusions.json"
DOSSIER_NAME = "routing_rmux30_population_dossier.json"


class ImportError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ImportError(message)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
            + "\n").encode("ascii")


def identity(value):
    return routing_admission.canonical_value_identity(value)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def reference(name, files):
    return {"path": name, "sha256": sha256_bytes(files[name])}


def load_exact(path, expected_hash, label):
    raw = path.read_bytes()
    require(sha256_bytes(raw) == expected_hash, "%s hash mismatch" % label)
    try:
        return raw, json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportError("%s is invalid JSON" % label) from exc


def validate_sources(review_path, receipt_path):
    review_raw, review = load_exact(review_path, REVIEW_SHA256, "result review")
    receipt_raw, receipt = load_exact(receipt_path, RECEIPT_SHA256, "approval receipt")
    body = dict(review)
    declared = body.pop("dossier_identity", None)
    require(declared == REVIEW_IDENTITY and identity(body) == REVIEW_IDENTITY,
            "result review identity mismatch")
    body = dict(receipt)
    declared = body.pop("receipt_identity", None)
    require(declared == RECEIPT_IDENTITY and identity(body) == RECEIPT_IDENTITY,
            "approval receipt identity mismatch")
    require(receipt.get("state") == "approved"
            and receipt.get("decision") == "approve-exact-six-row-experimental-import"
            and receipt["pending_result_review"]["sha256"] == REVIEW_SHA256
            and receipt["pending_result_review"]["dossier_identity"] == REVIEW_IDENTITY,
            "approval receipt scope mismatch")
    proposals = review.get("proposed_admissions", [])
    exclusions = review.get("terminal_exclusions", [])
    require(len(proposals) == 6 and len(exclusions) == 2,
            "review population accounting mismatch")
    require([row["proposal_identity"] for row in proposals]
            == receipt["proposal_identities"],
            "approval does not bind the exact proposal order")
    require(sorted(item["edge_id"] for item in exclusions)
            == sorted(receipt["excluded_edge_ids"]),
            "approval does not bind the exact exclusions")
    require(review["accounting"] == {
        "authorized_full_vendor_builds": 14,
        "excluded_rows": 2,
        "fresh_pairs": 14,
        "hardware_operations": 0,
        "new_vendor_builds_after_execution": 0,
        "observed_full_vendor_builds": 14,
        "passing_pairs": 12,
        "proposed_rows": 6,
        "terminal_pairs": 2,
    }, "review accounting mismatch")
    require(review["candidate_rows_admitted"] == 0
            and review["release_selector_changed"] is False
            and review["decision_scope"]["release_strict_permission"] == "denied",
            "source review is not a no-admission fail-closed proposal")
    return review_raw, review, receipt_raw, receipt


def build(review_path, receipt_path):
    review_raw, review, receipt_raw, receipt = validate_sources(
        review_path, receipt_path)
    files = {SOURCE_NAME: receipt_raw}

    evidence = {
        "schema": "agamemnon.routing-rmux30-holdout-evidence.v1",
        "source_result_review_sha256": REVIEW_SHA256,
        "source_result_review_identity": REVIEW_IDENTITY,
        "execution_authority": review["execution_authority"],
        "execution_history": review["execution_history"],
        "result_bindings": review["result_bindings"],
        "accounting": review["accounting"],
        "passing_edge_ids": sorted(
            item["edge_id"] for item in review["proposed_admissions"]
            if item["review_basis"] == "fresh-post-pattern-holdout-pass"
        ),
        "full_apparatus_edge_ids": sorted(
            item["edge_id"] for item in review["proposed_admissions"]
            if item["review_basis"] == "approved-full-apparatus-gate6"
        ),
        "non_claim": review["non_claim"],
    }
    evidence["evidence_identity"] = identity(evidence)
    files[EVIDENCE_NAME] = encode(evidence)

    negative = {
        "schema": "agamemnon.routing-rmux30-terminal-exclusions.v1",
        "source_result_review_sha256": REVIEW_SHA256,
        "exclusions": review["terminal_exclusions"],
        "required_disposition": (
            "Both rows remain terminal and fail-closed; mapping absence is not "
            "a silicon or feature finding."
        ),
    }
    negative["exclusion_identity"] = identity(negative)
    files[NEGATIVE_NAME] = encode(negative)

    dossier = {
        "schema": "agamemnon.routing-rmux30-population-dossier.v1",
        "source_result_review": {
            "sha256": REVIEW_SHA256, "dossier_identity": REVIEW_IDENTITY,
        },
        "source_approval": {
            "sha256": RECEIPT_SHA256, "receipt_identity": RECEIPT_IDENTITY,
        },
        "accounting": review["accounting"],
        "proposal_identities": receipt["proposal_identities"],
        "excluded_edge_ids": receipt["excluded_edge_ids"],
        "permission": {
            "allowed": "experimental-strict",
            "default_selection": "denied",
            "release_strict": "denied",
        },
        "scope": {"device": "AGRV2KL48", "package": "L48",
                  "composition": "exact-edge-only"},
        "non_claim": review["non_claim"],
    }
    dossier["dossier_identity"] = identity(dossier)
    files[DOSSIER_NAME] = encode(dossier)

    source_ref = reference(SOURCE_NAME, files)
    evidence_ref = reference(EVIDENCE_NAME, files)
    negative_ref = reference(NEGATIVE_NAME, files)
    dossier_ref = reference(DOSSIER_NAME, files)
    rows = []
    for proposal in review["proposed_admissions"]:
        edge_id = proposal["edge_id"]
        row = {
            "feature_id": routing_admission.OPTION_NAME,
            "edge_id": edge_id,
            "row_identity": "",
            "route": proposal["route"],
            "encoding": proposal["encoding"],
            "registry_maturity": "experimental",
            "evidence_tier": "differentially_validated",
            "claim_domain": "exact differential routing-selector encoding",
            "strict_permission": "experimental-strict",
            "scope": proposal["scope"],
            "evidence_refs": [evidence_ref],
            "approval": {
                "state": "approved", "approved_by": "Brian Benchoff",
                "review_date": REVIEW_DATE,
                "source_admission": source_ref,
                "dossier": dossier_ref,
                "dossier_identity": dossier["dossier_identity"],
                "admission_review": None,
            },
            "conflict_count": 0, "unknown_count": 0,
            "terminal_edge_overlap_count": 0,
            "retained_negative_refs": [negative_ref],
        }
        require(routing_admission.canonical_edge_id(row["route"]) == edge_id,
                "proposal edge ID is not canonical: %s" % edge_id)
        approval = {
            "schema": "agamemnon.routing-selector-admission-approval.v1",
            "decision": "approve-experimental-routing-selector",
            "edge_id": edge_id, "route": row["route"],
            "encoding": row["encoding"],
            "evidence_tier": row["evidence_tier"],
            "registry_maturity": row["registry_maturity"],
            "strict_permission": row["strict_permission"],
            "approved_by": row["approval"]["approved_by"],
            "review_date": REVIEW_DATE,
            "source_admission": source_ref,
            "dossier": dossier_ref,
            "dossier_identity": dossier["dossier_identity"],
        }
        approval_name = "routing_rmux30_row_approval_%s.json" % edge_id[:12]
        files[approval_name] = encode(approval)
        row["approval"]["admission_review"] = reference(approval_name, files)
        row["row_identity"] = routing_admission.canonical_identity(row)
        rows.append(row)

    rows.sort(key=lambda item: item["edge_id"])
    manifest = {
        "accounting": {"admitted_rows": 6},
        "non_claim": (
            "Six exact AGRV2KL48/L48 differential selector rows; disabled by "
            "default and denied under release-strict policy."
        ),
        "permission": {
            "allowed": "experimental-strict",
            "default_selection": "denied",
            "release_strict": "denied",
        },
        "policy_version": "D0-v1",
        "provenance": {
            "state": "reviewed-import",
            "source_admission_manifest_sha256": RECEIPT_SHA256,
        },
        "rows": rows,
        "schema": routing_admission.SCHEMA,
        "scope": {"device": "AGRV2KL48", "package": "L48"},
    }
    routing_admission.validate_manifest(manifest)
    files[routing_admission.FILENAME] = encode(manifest)
    return files


def write(files, output_root):
    manifest = output_root / routing_admission.FILENAME
    require(manifest.is_file(), "public bootstrap manifest is missing")
    require(sha256_bytes(manifest.read_bytes()) == BOOTSTRAP_SHA256,
            "public routing admission is not the exact empty bootstrap")
    for name in files:
        path = output_root / name
        if name != routing_admission.FILENAME:
            require(not path.exists(), "refusing to overwrite %s" % path)
    for name, content in files.items():
        (output_root / name).write_bytes(content)


def verify(files, output_root):
    actual_names = set(files)
    for name, expected in files.items():
        path = output_root / name
        require(path.is_file() and path.read_bytes() == expected,
                "generated public artifact mismatch: %s" % name)
    rows = routing_admission.load_manifest(output_root)
    require(len(rows) == 6, "public loader did not authenticate six rows")
    return actual_names, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        files = build(args.review.resolve(), args.receipt.resolve())
        output = args.output_root.resolve()
        if args.verify:
            _, rows = verify(files, output)
        else:
            write(files, output)
            _, rows = verify(files, output)
        print(json.dumps({
            "status": "verified" if args.verify else "imported",
            "rows": len(rows),
            "manifest_sha256": sha256_bytes(files[routing_admission.FILENAME]),
            "row_identities": [row["row_identity"] for row in rows],
        }, sort_keys=True))
        return 0
    except (ImportError, OSError, ValueError,
            routing_admission.RoutingAdmissionError) as exc:
        print("import_rmux30_routing_admission: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
