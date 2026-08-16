import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "qualification" / "bram_x18_vendor_control_evidence.jsonl"


def record():
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]
    return next(row for row in rows
                if row["trial_id"] == "2026-08-16-bram-x18-rea-addressstall-transaction")


def test_logical_ports_are_not_misclassified_as_configuration_fields():
    row = record()
    assert row["classification"]["ReA"].startswith("logical hard-macro input")
    assert row["classification"]["AddressStallA"].startswith(
        "logical vendor hard-macro input")
    assert "workbench only" in row["classification"]["AddressStallA"]
    assert "AddressStallA" not in row["classification"]["configuration_semantics"]


def test_static_and_temporal_matrices_are_bounded_by_liveness():
    row = record()
    assert row["static_matrix"]["arms"] == 6
    assert row["temporal_matrix"]["arms"] == 4
    for matrix in (row["static_matrix"], row["temporal_matrix"]):
        assert matrix["result"] == "no hard-array mutation"
        assert "h1..h3 varied" in matrix["observed"]
        assert "0x000f0002" in matrix["observed"]
    assert row["result"] == (
        "pass_bounded_no_hard_write_rea_addressstall_and_tested_sequence")
    assert "no production BRAM write behavior is promoted" in row["consequence"]


def test_every_retained_manifest_and_image_hash_is_sha256():
    row = record()
    hashes = [row["static_matrix"]["manifest"]["sha256"],
              row["temporal_matrix"]["manifest"]["sha256"]]
    for matrix_name in ("static_matrix", "temporal_matrix"):
        for cases in row[matrix_name]["images"].values():
            hashes.extend(cases.values())
    assert len(hashes) == 12
    for digest in hashes:
        assert len(digest) == 64
        int(digest, 16)


def test_mux_ownership_and_selector_policy_remain_strict():
    policy = record()["selector_policy"]
    assert "zero cross-net mux ownership conflicts" in policy
    assert "zero unmapped, predicted, or legacy-absolute selectors" in policy
