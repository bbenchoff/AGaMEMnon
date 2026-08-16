import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "qualification" / "bram_x18_vendor_control_evidence.jsonl"


def record():
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]
    return next(row for row in rows
                if row["trial_id"] == "2026-08-16-bram-x18-exact-vendor-control-cube")


def test_full_control_cube_is_bounded_and_liveness_gated():
    row = record()
    truth = row["truth_table"]
    assert truth["arms"] == 32
    assert truth["result"] == "no hard-array mutation"
    assert "h1..h3 varied in every arm" in truth["observed"]
    assert row["result"] == "pass_bounded_no_hard_write_full_control_cube"
    assert "No production write behavior is promoted" in row["consequence"]


def test_vendor_oracle_is_structural_and_source_code_is_corrected():
    row = record()
    oracle = row["vendor_structural_oracle"]
    assert oracle["behavior_claimed"] is False
    assert "zero cross-net conflicts" in oracle["mux_ownership"]
    correction = row["terminal_code_correction"]
    assert "X16 TMUX13 codeword 104,111" in correction["correction"]
    assert "vendor X15 codeword 108,110" in correction["correction"]
    assert correction["single_variable_ab"]["only_non_crc_difference"] == (
        "raw bytes 72602 and 72718, the four TMUX13 selector bits")


def test_all_retained_artifact_hashes_are_sha256():
    row = record()
    hashes = [
        row["vendor_structural_oracle"][name]["sha256"]
        for name in ("image", "route", "macro")
    ]
    hashes.extend([
        row["terminal_code_correction"]["single_variable_ab"]["manifest"]["sha256"],
        row["truth_table"]["manifest"]["sha256"],
    ])
    for digest in hashes:
        assert len(digest) == 64
        int(digest, 16)
