"""The load-time-equivalent guard for ``agamemnon.engine.gate_claims``.

Mirrors ``tests/test_selector_injectivity.py``'s shape and purpose, applied to
claims instead of selector-table defects: a policy annotated with
``# CLAIM: <id>`` must resolve to a claim that is registered and not retired.
This is the enforcement half of the module -- without it, the registry is a
document nobody reads, which is exactly the failure this whole mechanism
exists to stop (``AGAMEMNON_STRICT_GATE`` cited a claim retired 2026-08-13 for
eight more days before anyone noticed).
"""

from pathlib import Path

import pytest

from agamemnon.engine import gate_claims as GC


ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# The registry itself is well-formed
# --------------------------------------------------------------------------

def test_every_claim_has_a_stable_id_statement_and_evidence():
    seen = set()
    for claim in GC.CLAIMS:
        assert claim.id and claim.id not in seen, "duplicate or empty id"
        seen.add(claim.id)
        assert claim.statement.strip()
        assert claim.evidence.strip()
        assert claim.status in ("live", "disputed", "retired")


def test_retired_claims_record_when_and_by():
    for claim in GC.CLAIMS:
        if claim.status == "retired":
            assert claim.retired_on.strip(), (
                "%s: retired with no retired_on date" % claim.id)
            assert claim.retired_by.strip(), (
                "%s: retired with no retired_by attribution" % claim.id)


def test_live_and_disputed_claims_do_not_carry_retirement_fields():
    """A claim is either retired with a date, or it isn't -- no in-between."""
    for claim in GC.CLAIMS:
        if claim.status != "retired":
            assert claim.retired_on == ""
            assert claim.retired_by == ""


def test_see_also_links_resolve():
    for claim in GC.CLAIMS:
        for other in claim.see_also:
            assert other in GC.BY_ID, (
                "%s: see_also references unknown claim %r" % (claim.id, other))


def test_the_split_conduction_claim_is_representable():
    """The worked example the module documents: one conflated claim split in two.

    ``dead-edge-catalogue-2026`` (retired) and
    ``per-position-conduction-witness-required`` (live) must each exist, have
    opposite status, and cross-reference each other -- proving the registry
    can retire exactly the part of a claim that died while keeping the
    adjacent, still-true part live.
    """
    catalogue = GC.BY_ID["dead-edge-catalogue-2026"]
    witness = GC.BY_ID["per-position-conduction-witness-required"]
    assert catalogue.status == "retired"
    assert witness.status == "live"
    assert witness.id in catalogue.see_also
    assert catalogue.id in witness.see_also


# --------------------------------------------------------------------------
# Citation resolution: the actual guard
# --------------------------------------------------------------------------

def test_check_citation_accepts_a_live_claim():
    claim = GC.check_citation("per-position-conduction-witness-required")
    assert claim.status == "live"


def test_check_citation_accepts_a_disputed_claim():
    claim = GC.check_citation("direct-d-four-site-pool-is-hardware-limit")
    assert claim.status == "disputed"


def test_check_citation_rejects_a_retired_claim():
    """Demonstrates the guard: point a citation at a retired claim and watch it fail.

    This is the core of the mechanism -- a citation is only useful if pointing
    it at dead evidence is actually caught, not merely possible to catch.
    """
    with pytest.raises(GC.ClaimLedgerError) as excinfo:
        GC.check_citation("dead-edge-catalogue-2026")
    message = str(excinfo.value)
    assert "retired" in message
    assert "2026-08-13" in message


def test_check_citation_rejects_an_unknown_claim():
    with pytest.raises(GC.ClaimLedgerError) as excinfo:
        GC.check_citation("this-claim-does-not-exist")
    assert "unknown claim" in str(excinfo.value)


# --------------------------------------------------------------------------
# File-level audit: what actually runs against the shipped source
# --------------------------------------------------------------------------

def test_the_shipped_annotated_files_cite_only_live_or_disputed_claims():
    """The real guard: today's tree must be clean.

    If a future edit points one of these annotations at a claim that gets
    retired later, this is the test that turns red.
    """
    citations, errors = GC.audit()
    assert citations, "expected at least one CLAIM: annotation in the shipped tree"
    assert errors == [], "a shipped policy cites a retired or unknown claim:\n" + "\n".join(errors)


def test_enforce_accepts_the_shipped_tree():
    assert GC.enforce() is True


def test_each_seeded_annotation_point_is_actually_cited():
    """Coverage in the other direction: every claim meant to back real code does.

    Guards against the annotation comment silently disappearing (e.g. a
    careless edit) while the registry entry survives, which would make the
    registry describe code that no longer exists.
    """
    citations, _ = GC.audit()
    cited_ids = {claim_id for _, _, claim_id in citations}
    expected = {
        "per-position-conduction-witness-required",
        "xbar-conduction-even-slot-shape",
        "direct-d-four-site-pool-is-hardware-limit",
        "mcu-ahb-request-control-shared-source-oracle",
        "mcu-ahb-request-control-independent-ff-oracle",
        "mcu-ahb-haddr2-independent-register-oracle",
    }
    missing = expected - cited_ids
    assert not missing, "expected annotation(s) not found in the shipped tree: %s" % missing


def test_the_retired_claim_is_not_cited_anywhere_in_the_shipped_tree():
    """The flip side of the enforcement: nothing should currently point at it.

    If this ever fails, a real policy started citing a retired claim -- which
    is exactly the failure this module exists to catch before it ships.
    """
    citations, _ = GC.audit()
    cited_ids = {claim_id for _, _, claim_id in citations}
    assert "dead-edge-catalogue-2026" not in cited_ids


# --------------------------------------------------------------------------
# Citation syntax, on synthetic text -- independent of the shipped tree
# --------------------------------------------------------------------------

def test_citations_in_text_finds_python_and_cpp_comment_styles():
    text = (
        "# CLAIM: per-position-conduction-witness-required\n"
        "STRICT_GATE = True\n"
        "// CLAIM: xbar-conduction-even-slot-shape\n"
        "bool strict_allows_odd = true;\n"
    )
    found = GC.citations_in_text(text)
    assert found == [
        (1, "per-position-conduction-witness-required"),
        (3, "xbar-conduction-even-slot-shape"),
    ]


def test_audit_reports_a_retired_citation_in_a_synthetic_file(tmp_path):
    """End-to-end: a fresh file citing a retired claim is caught by audit()."""
    bad = tmp_path / "synthetic_policy.py"
    bad.write_text(
        "# CLAIM: dead-edge-catalogue-2026\n"
        "SOME_GATE = True\n",
        encoding="utf-8",
    )
    citations, errors = GC.audit(root=str(tmp_path), files=("synthetic_policy.py",))
    assert citations == [("synthetic_policy.py", 1, "dead-edge-catalogue-2026")]
    assert len(errors) == 1
    assert "retired" in errors[0]
    with pytest.raises(GC.ClaimLedgerError):
        GC.enforce(root=str(tmp_path), files=("synthetic_policy.py",))


def test_audit_reports_an_unknown_citation_in_a_synthetic_file(tmp_path):
    bad = tmp_path / "synthetic_policy.py"
    bad.write_text("# CLAIM: totally-made-up-id\n", encoding="utf-8")
    citations, errors = GC.audit(root=str(tmp_path), files=("synthetic_policy.py",))
    assert len(citations) == 1
    assert len(errors) == 1
    assert "unknown claim" in errors[0]


def test_audit_is_clean_for_a_synthetic_file_citing_a_live_claim(tmp_path):
    good = tmp_path / "synthetic_policy.py"
    good.write_text(
        "# CLAIM: per-position-conduction-witness-required\n", encoding="utf-8")
    citations, errors = GC.audit(root=str(tmp_path), files=("synthetic_policy.py",))
    assert len(citations) == 1
    assert errors == []
    assert GC.enforce(root=str(tmp_path), files=("synthetic_policy.py",)) is True


def test_an_unannotated_file_is_invisible_to_the_audit_not_a_violation(tmp_path):
    """Fail closed on a bad citation, never on the ABSENCE of one."""
    plain = tmp_path / "synthetic_policy.py"
    plain.write_text("SOME_GATE = os.environ.get('X')\n", encoding="utf-8")
    citations, errors = GC.audit(root=str(tmp_path), files=("synthetic_policy.py",))
    assert citations == []
    assert errors == []


def test_a_missing_file_in_the_annotated_list_is_not_an_error(tmp_path):
    citations, errors = GC.audit(root=str(tmp_path), files=("does_not_exist.py",))
    assert citations == []
    assert errors == []


# --------------------------------------------------------------------------
# Construction-time validation of the Claim dataclass itself
# --------------------------------------------------------------------------

def test_a_retired_claim_without_dates_is_rejected_at_construction():
    with pytest.raises(ValueError):
        GC.Claim(id="x", statement="s", evidence="e", status="retired")


def test_an_unknown_status_is_rejected_at_construction():
    with pytest.raises(ValueError):
        GC.Claim(id="x", statement="s", evidence="e", status="mostly-true")


def test_empty_statement_or_evidence_is_rejected_at_construction():
    with pytest.raises(ValueError):
        GC.Claim(id="x", statement="", evidence="e", status="live")
    with pytest.raises(ValueError):
        GC.Claim(id="x", statement="s", evidence="  ", status="live")
