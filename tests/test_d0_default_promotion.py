"""D0 default-promotion amendment: staged behind an un-approved hash gate.

These tests pin the amendment invariants the directive requires:

* gate UN-approved  -> current behavior (differentially_validated default-denied);
* gate approved     -> witnessed approved-population routing rows become
  default-selectable, with no opt-in flag, including future approved waves;
* predicted/decoded/unwitnessed material -> never default-eligible, either state;
* L48 scope preserved and non-negotiable;
* demote-on-silicon-disagreement removes a promoted row from the default set.

The witnessed rows exercised here are IOTILE RMUX30 architecture-pip suppliers --
structurally identical to the six packaged rows -- built in a temporary chipdb so
the shipped chipdb keeps its gate un-approved and the live default unchanged.
"""

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agamemnon.engine import hil_audit, routing_admission
from agamemnon.engine.claim_policy import (
    ClaimPolicyError,
    _permission_error,
    evaluate_policy,
)
from agamemnon.engine.registry import POLICY_VERSION, ClaimMetadata, options_from


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
OPTION = routing_admission.OPTION_NAME


# --------------------------------------------------------------------------- #
# Fixtures for a temporary reviewed admission + amendment approval.
# --------------------------------------------------------------------------- #

def _iotile_row(src_x, y, set_sel, clear_sel):
    """A witnessed IOTILE RMUX30 architecture-pip supplier (packaged row class)."""
    owned = sorted({set_sel, clear_sel})
    row = {
        "feature_id": OPTION,
        "edge_id": "0" * 64,
        "row_identity": "0" * 64,
        "route": {
            "source": {"tile": "LogicTILE", "x": src_x, "y": y,
                       "family": "RMUX", "index": 20},
            "destination": {"tile": "IOTILE", "x": 0, "y": y,
                            "family": "RMUX", "index": 30},
        },
        "encoding": {
            "owner_tile": "IOTILE", "owner_x": 0, "owner_y": y, "cfg": "CFG_RMUX3",
            "set_selectors": [set_sel], "clear_selectors": [clear_sel],
            "owned_selectors": owned,
        },
        "registry_maturity": "experimental",
        "evidence_tier": "differentially_validated",
        "claim_domain": "exact differential routing-selector encoding",
        "strict_permission": "experimental-strict",
        "scope": {"device": "AGRV2KL48", "package": "L48",
                  "coordinates": "exact-route-and-owner-coordinates",
                  "composition": "exact-edge-only"},
        "evidence_refs": [],
        "approval": {},
        "conflict_count": 0, "unknown_count": 0, "terminal_edge_overlap_count": 0,
        "retained_negative_refs": [],
    }
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    return row


def _logic_mesh_row():
    """A differentially_validated row that is NOT an architecture-pip supplier."""
    row = {
        "feature_id": OPTION,
        "edge_id": "0" * 64,
        "row_identity": "0" * 64,
        "route": {
            "source": {"tile": "LogicTILE", "x": 5, "y": 4,
                       "family": "RMUX", "index": 21},
            "destination": {"tile": "LogicTILE", "x": 1, "y": 4,
                            "family": "RMUX", "index": 31},
        },
        "encoding": {
            "owner_tile": "LogicTILE", "owner_x": 2, "owner_y": 4, "cfg": "CFG_RMUX7",
            "set_selectors": [45, 46], "clear_selectors": [43],
            "owned_selectors": [43, 45, 46],
        },
        "registry_maturity": "experimental",
        "evidence_tier": "differentially_validated",
        "claim_domain": "exact differential routing-selector encoding",
        "strict_permission": "experimental-strict",
        "scope": {"device": "AGRV2KL48", "package": "L48",
                  "coordinates": "exact-route-and-owner-coordinates",
                  "composition": "exact-edge-only"},
        "evidence_refs": [],
        "approval": {},
        "conflict_count": 0, "unknown_count": 0, "terminal_edge_overlap_count": 0,
        "retained_negative_refs": [],
    }
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    return row


def _build_chipdb(root, rows, *, populations=None, with_approval,
                  promoted=None, admission_sha_override=None, scope_override=None,
                  approved_by="Brian Benchoff", review_date="2026-08-09",
                  policy_version=None, extra_field=False):
    root.mkdir(parents=True, exist_ok=True)
    populations = populations or ["p0"] * len(rows)

    def retain(name, value):
        path = root / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    evidence = retain("evidence.json", {"evidence": "public"})
    negative = retain("negative.json", {"terminal_overlap": 0})
    source = retain("source.json", {"rows": len(rows)})

    dossier_refs, dossier_ids = {}, {}
    for pop in dict.fromkeys(populations):
        base = {"campaign": "public-differential", "population": pop}
        identity = routing_admission.canonical_value_identity(base)
        full = dict(base, dossier_identity=identity)
        dossier_refs[pop] = retain("dossier_%s.json" % pop, full)
        dossier_ids[pop] = identity

    for index, (row, pop) in enumerate(zip(rows, populations)):
        row["evidence_refs"] = [evidence]
        row["retained_negative_refs"] = [negative]
        row["approval"] = {
            "state": "approved", "approved_by": "Brian Benchoff",
            "review_date": "2026-08-09",
            "source_admission": source,
            "dossier": dossier_refs[pop],
            "dossier_identity": dossier_ids[pop],
            "admission_review": {"path": "placeholder", "sha256": "0" * 64},
        }
        review = {
            "schema": "agamemnon.routing-selector-admission-approval.v1",
            "decision": "approve-experimental-routing-selector",
            "edge_id": row["edge_id"], "route": row["route"],
            "encoding": row["encoding"], "evidence_tier": row["evidence_tier"],
            "registry_maturity": row["registry_maturity"],
            "strict_permission": row["strict_permission"],
            "approved_by": "Brian Benchoff", "review_date": "2026-08-09",
            "source_admission": source, "dossier": dossier_refs[pop],
            "dossier_identity": dossier_ids[pop],
        }
        row["approval"]["admission_review"] = retain("approval_%d.json" % index, review)
        row["row_identity"] = routing_admission.canonical_identity(row)

    manifest = {
        "accounting": {"admitted_rows": len(rows)},
        "non_claim": "Exact rows; disabled by default and denied under release-strict policy.",
        "permission": {"allowed": "experimental-strict",
                       "default_selection": "denied", "release_strict": "denied"},
        "policy_version": POLICY_VERSION,
        "provenance": {"state": "reviewed-import",
                       "source_admission_manifest_sha256": source["sha256"]},
        "rows": rows,
        "schema": routing_admission.SCHEMA,
        "scope": {"device": "AGRV2KL48", "package": "L48"},
    }
    (root / routing_admission.FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    wire_rows, cell_keys = set(), []
    seen_cells = set()
    for row in rows:
        s, d, e = row["route"]["source"], row["route"]["destination"], row["encoding"]
        for comp in (s, d):
            wire_rows.add((comp["tile"], comp["x"], comp["y"],
                           "%s%02d" % (comp["family"], comp["index"])))
        if (e["owner_x"], e["owner_y"]) not in {(s["x"], s["y"]), (d["x"], d["y"])}:
            wire_rows.add((e["owner_tile"], e["owner_x"], e["owner_y"], "RMUX00"))
        for sel in e["owned_selectors"]:
            key = (e["owner_x"], e["owner_y"], e["cfg"], sel)
            if key not in seen_cells:
                seen_cells.add(key)
                cell_keys.append(key)
    with (root / "wires.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("tile", "x", "y", "resource"))
        writer.writeheader()
        for tile, x, y, resource in sorted(wire_rows):
            writer.writerow({"tile": tile, "x": x, "y": y, "resource": resource})
    with (root / "pips_full.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("x", "y", "mux", "sel", "byte", "mask"))
        writer.writeheader()
        for offset, (x, y, mux, sel) in enumerate(cell_keys):
            writer.writerow({"x": x, "y": y, "mux": mux, "sel": sel,
                             "byte": 100 + offset, "mask": 1 << (offset % 8)})

    if with_approval:
        admission_sha = admission_sha_override or routing_admission.manifest_identity(root)
        approval = {
            "schema": routing_admission.DEFAULT_PROMOTION_SCHEMA,
            "decision": routing_admission.DEFAULT_PROMOTION_DECISION,
            "state": "approved",
            "approved_by": approved_by,
            "review_date": review_date,
            "policy_version": policy_version or POLICY_VERSION,
            "routing_selector_admission_sha256": admission_sha,
            "promoted_population_dossier_identities":
                promoted if promoted is not None else sorted(dossier_ids.values()),
            "scope": scope_override or {"device": "AGRV2KL48", "package": "L48",
                                        "claim": "routing-selection-only"},
        }
        if extra_field:
            approval["unexpected"] = True
        (root / routing_admission.DEFAULT_PROMOTION_FILENAME).write_text(
            json.dumps(approval, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return root, dossier_ids


def _default_options(root):
    # Default surface: release-strict policy (registry default), L48, no opt-in.
    return options_from({"AGAMEMNON_DATA": str(root), "AGAMEMNON_DEVICE": "AGRV2KL48"})


def _diff_claim(**changes):
    base = ClaimMetadata(
        evidence_tier="differentially_validated",
        claim_domain="exact differential routing-selector encoding",
        claim_scope="AGRV2KL48/L48 exact edge",
        policy_version=POLICY_VERSION,
        approval_state="approved",
        approved_by="Brian Benchoff",
        review_date="2026-08-09",
        individual_only=False,
        emits=True,
        evidence_refs=("evidence.json",),
    )
    return replace(base, **changes)


# --------------------------------------------------------------------------- #
# (a) Gate UN-approved -> current behavior preserved.
# --------------------------------------------------------------------------- #

def test_live_shipped_gate_is_unapproved_and_default_denies_routing_rows():
    assert not (CHIPDB / routing_admission.DEFAULT_PROMOTION_FILENAME).exists()
    assert routing_admission.default_promotion_populations(CHIPDB) == frozenset()
    options = options_from({})
    assert routing_admission.selected_rows(options, CHIPDB) == ()
    decision = evaluate_policy(options)
    assert decision.policy == "release-strict"
    assert not [row for row in decision.selected if row["kind"] == "routing_selector"]


def test_gate_unapproved_denies_temporary_witnessed_rows(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=False)
    options = _default_options(root)
    assert routing_admission.selected_rows(options, root) == ()
    decision = evaluate_policy(options)
    assert not [row for row in decision.selected if row["kind"] == "routing_selector"]


def test_differentially_validated_is_default_denied_without_amendment():
    claim = _diff_claim()
    # Registry maturity for a routing row is experimental; under release-strict
    # and without the amendment flag it fails closed exactly as before.
    assert "release-strict requires release maturity" in _permission_error(
        OPTION, "experimental", claim, "release-strict", ()
    )


# --------------------------------------------------------------------------- #
# (b) Gate approved -> witnessed rows default-selectable, incl. future waves.
# --------------------------------------------------------------------------- #

def test_gate_approved_promotes_witnessed_rows_to_default(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44), _iotile_row(4, 4, 45, 43)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True)
    options = _default_options(root)

    selected = routing_admission.selected_rows(options, root)
    assert {row["row_identity"] for row in selected} == {row["row_identity"] for row in rows}

    decision = evaluate_policy(options)
    assert decision.policy == "release-strict"
    picked = [row for row in decision.selected if row["kind"] == "routing_selector"]
    assert len(picked) == 2
    assert any(row["kind"] == "routing_selector_manifest" for row in decision.selected)


def test_amendment_permission_path_admits_witnessed_claim_under_release_strict():
    claim = _diff_claim()
    assert _permission_error(
        OPTION, "experimental", claim, "release-strict", (), default_promotion=True
    ) is None


def test_future_approved_wave_rows_also_promote(tmp_path):
    # Two distinct population wave-dossiers; the amendment promotes both.
    rows = [_iotile_row(4, 2, 45, 44), _iotile_row(4, 4, 45, 43)]
    root, dossier_ids = _build_chipdb(
        tmp_path, rows, populations=["wave-r5", "wave-r6"], with_approval=True
    )
    selected = routing_admission.selected_rows(_default_options(root), root)
    assert len(selected) == 2


def test_only_promoted_populations_reach_default(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44), _iotile_row(4, 4, 45, 43)]
    root, dossier_ids = _build_chipdb(
        tmp_path, rows, populations=["approved-wave", "unapproved-wave"],
        with_approval=True, promoted=[
            routing_admission.canonical_value_identity(
                {"campaign": "public-differential", "population": "approved-wave"}
            )
        ],
    )
    selected = routing_admission.selected_rows(_default_options(root), root)
    assert len(selected) == 1
    assert selected[0]["route"]["source"]["y"] == 2


def test_packaged_six_rows_are_exactly_the_promotable_witnessed_class():
    rows = routing_admission.load_manifest(CHIPDB)
    assert len(rows) == 6
    assert all(routing_admission.supplies_architecture_pip(row) for row in rows)
    assert all(row["evidence_tier"] == "differentially_validated" for row in rows)
    # One approved population wave-dossier; approving it would promote all six.
    assert len({row["approval"]["dossier_identity"] for row in rows}) == 1


# --------------------------------------------------------------------------- #
# (c) Predicted / decoded / unwitnessed never default-eligible, either state.
# --------------------------------------------------------------------------- #

def test_decoded_claim_cannot_be_default_promoted_even_if_flag_forced():
    decoded = _diff_claim(evidence_tier="decoded")
    assert _permission_error(
        OPTION, "experimental", decoded, "release-strict", (), default_promotion=True
    ) is not None
    conflicted = _diff_claim(conflict_count=1)
    assert _permission_error(
        OPTION, "experimental", conflicted, "release-strict", (), default_promotion=True
    ) is not None
    unapproved = _diff_claim(approval_state="unapproved", approved_by=None, review_date=None)
    assert _permission_error(
        OPTION, "experimental", unapproved, "release-strict", (), default_promotion=True
    ) is not None


def test_non_architecture_pip_differential_row_is_never_default_selected(tmp_path):
    # A witnessed logic-mesh row is differentially_validated and approved, but it
    # does not supply an architecture pip, so it never reaches the default graph.
    rows = [_logic_mesh_row()]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True)
    assert routing_admission.selected_rows(_default_options(root), root) == ()


def test_default_promotion_is_inactive_outside_release_strict(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True)
    # experimental-strict without the opt-in flag: no auto-promotion.
    options = options_from({
        "AGAMEMNON_DATA": str(root), "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_STRICT_POLICY": "experimental-strict",
    })
    assert routing_admission.selected_rows(options, root) == ()


def test_research_unsafe_stays_the_only_flag_gated_predicted_surface():
    # Unchanged: research-unsafe still requires its explicit gate and never
    # becomes the default (release-strict) policy.
    with pytest.raises(ClaimPolicyError, match="AGAMEMNON_RESEARCH_UNSAFE=1"):
        evaluate_policy(options_from({"AGAMEMNON_STRICT_POLICY": "research-unsafe"}))


# --------------------------------------------------------------------------- #
# (d) L48 scope preserved and non-negotiable.
# --------------------------------------------------------------------------- #

def test_default_promotion_does_not_activate_off_l48(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True)
    options = options_from({
        "AGAMEMNON_DATA": str(root), "AGAMEMNON_DEVICE": "AGRV2KQ32",
        "AGAMEMNON_STRICT_POLICY": "research-unsafe",
        "AGAMEMNON_RESEARCH_UNSAFE": "1",
    })
    assert routing_admission.selected_rows(options, root) == ()


def test_amendment_approval_scope_must_stay_l48_routing_selection_only(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(
        tmp_path, rows, with_approval=True,
        scope_override={"device": "AGRV2KL100", "package": "L100",
                        "claim": "routing-selection-only"},
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="L48 routing-selection-only"):
        routing_admission.selected_rows(_default_options(root), root)


# --------------------------------------------------------------------------- #
# Amendment approval binds the exact reviewed bytes (fail-closed hash gate).
# --------------------------------------------------------------------------- #

def test_amendment_approval_must_bind_exact_admission_hash(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(
        tmp_path, rows, with_approval=True, admission_sha_override="a" * 64
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="exact reviewed population"):
        routing_admission.selected_rows(_default_options(root), root)


def test_amendment_approval_cannot_promote_unknown_population(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(
        tmp_path, rows, with_approval=True, promoted=["b" * 64]
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="absent from the reviewed"):
        routing_admission.selected_rows(_default_options(root), root)


@pytest.mark.parametrize("kwargs, phrase", [
    ({"approved_by": "Mallory"}, "explicit owner approval"),
    ({"review_date": "2099-01-01"}, "future"),
    ({"policy_version": "D0-v0"}, "policy version"),
    ({"extra_field": True}, "field set mismatch"),
])
def test_amendment_approval_rejects_tampered_authority(tmp_path, kwargs, phrase):
    rows = [_iotile_row(4, 2, 45, 44)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True, **kwargs)
    with pytest.raises(routing_admission.RoutingAdmissionError, match=phrase):
        routing_admission.selected_rows(_default_options(root), root)


# --------------------------------------------------------------------------- #
# (e) Demote-on-silicon-disagreement removes a promoted row from the default set.
# --------------------------------------------------------------------------- #

def test_silicon_disagreement_demotes_a_promoted_default_row(tmp_path):
    rows = [_iotile_row(4, 2, 45, 44), _iotile_row(4, 4, 45, 43)]
    root, _ = _build_chipdb(tmp_path, rows, with_approval=True)
    promoted = routing_admission.selected_rows(_default_options(root), root)
    assert len(promoted) == 2
    disagreeing = promoted[0]["row_identity"]

    def sampler(row):
        return hil_audit.SiliconSample(
            row["row_identity"], row["edge_id"], observable=True,
            agrees=row["row_identity"] != disagreeing,
            detail="" if row["row_identity"] != disagreeing else "board disagreed",
        )

    outcome = hil_audit.audit_default_rows(promoted, sampler)
    assert [row["row_identity"] for row in outcome.demoted] == [disagreeing]
    assert outcome.retained_negatives[0]["row_identity"] == disagreeing
    remaining = hil_audit.demote_on_disagreement(
        promoted, [row["row_identity"] for row in outcome.demoted]
    )
    assert disagreeing not in {row["row_identity"] for row in remaining}
    assert len(remaining) == 1
