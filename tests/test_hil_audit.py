import pytest

from agamemnon.engine import hil_audit
from agamemnon.engine.hil_audit import (
    SiliconSample,
    audit_default_rows,
    demote_on_disagreement,
)


def _row(identity, edge="e"):
    return {"row_identity": identity, "edge_id": edge}


def test_agreeing_row_is_confirmed_and_retained():
    rows = [_row("a")]
    outcome = audit_default_rows(
        rows, lambda r: SiliconSample(r["row_identity"], r["edge_id"], True, True)
    )
    assert outcome.retained == tuple(rows)
    assert outcome.confirmed == ("a",)
    assert outcome.demoted == () and outcome.retained_negatives == ()


def test_silicon_disagreement_demotes_row_as_first_class_retained_negative():
    rows = [_row("a"), _row("b")]

    def sampler(r):
        agrees = r["row_identity"] != "b"
        return SiliconSample(
            r["row_identity"], r["edge_id"], True, agrees,
            detail="" if agrees else "silicon read mismatch",
        )

    outcome = audit_default_rows(rows, sampler)
    assert [r["row_identity"] for r in outcome.retained] == ["a"]
    assert [r["row_identity"] for r in outcome.demoted] == ["b"]
    assert len(outcome.retained_negatives) == 1
    negative = outcome.retained_negatives[0]
    assert negative["row_identity"] == "b"
    assert negative["reason"] == "silicon-disagreement"
    assert negative["finding"] == "first-class"
    assert negative["schema"] == hil_audit.RETAINED_NEGATIVE_SCHEMA
    assert negative["detail"] == "silicon read mismatch"


def test_unobservable_row_is_retained_not_demoted():
    rows = [_row("a")]
    outcome = audit_default_rows(
        rows, lambda r: SiliconSample(r["row_identity"], r["edge_id"], False, False)
    )
    assert outcome.retained == tuple(rows)
    assert outcome.unobserved == ("a",)
    assert outcome.demoted == () and outcome.retained_negatives == ()


def test_demote_on_disagreement_removes_only_flagged_rows():
    rows = [_row("a"), _row("b"), _row("c")]
    kept = demote_on_disagreement(rows, {"b"})
    assert [r["row_identity"] for r in kept] == ["a", "c"]


def test_sampler_contract_is_enforced():
    rows = [_row("a")]
    with pytest.raises(ValueError):
        audit_default_rows(
            rows, lambda r: SiliconSample("wrong-identity", r["edge_id"], True, True)
        )
    with pytest.raises(TypeError):
        audit_default_rows(rows, lambda r: "not a sample")


def test_production_sram_sampler_is_a_loud_todo_stub():
    with pytest.raises(NotImplementedError):
        hil_audit.silicon_sram_sampler(_row("a"))
