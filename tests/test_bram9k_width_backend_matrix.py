import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "agamemnon" / "chipdb" / "bram9k_width_backend_matrix.json"
PORTB_MATRIX = ROOT / "agamemnon" / "chipdb" / "bram9k_portb_width_backend_matrix.json"


def test_bram9k_width_backend_matrix_preserves_the_negative_control():
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert data["summary"] == {
        "cases": 7,
        "model_valid_candidates_accepted": 6,
        "model_valid_candidates_total": 6,
        "model_invalid_candidate_accepted": True,
        "repeat_runs_per_case": 2,
        "cases_with_deterministic_artifact_hashes": 0,
    }
    assert "may not enforce" in data["non_claim"]


def test_bram9k_width_codes_are_retained_in_both_vendor_runs():
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    for case in data["cases"]:
        assert case["backend_accepted_both_runs"] is True
        assert len(case["trials"]) == 2
        for trial in case["trials"]:
            assert trial["vendor_fatals"] == 0
            assert trial["vendor_errors"] == 0
            assert trial["routed_parameter_code"] == case["porta_width_code"]
            assert trial["placed_bram_tile"] == [13, 4]
            assert trial["bitstream_parameter_code"] == case["porta_width_code"]
            assert trial["bitstream_parameter_preserved"] is True
    invalid = next(case for case in data["cases"] if case["label"] == "model_invalid")
    assert invalid["model_valid_candidate"] is False
    assert invalid["porta_width_code"] == "00001"


def test_portb_width_matrix_preserves_candidates_and_negative_control():
    data = json.loads(PORTB_MATRIX.read_text(encoding="utf-8"))
    assert data["parameter"] == "PORTB_WIDTH"
    assert data["summary"]["model_valid_candidates_accepted"] == 6
    assert data["summary"]["model_invalid_candidate_accepted"] is True
    for case in data["cases"]:
        assert case["parameter_code"] == case["portb_width_code"]
        assert case["backend_accepted_both_runs"] is True
        for trial in case["trials"]:
            assert trial["routed_parameter_code"] == case["portb_width_code"]
            assert trial["placed_bram_tile"] == [13, 4]
            assert trial["bitstream_parameter_code"] == case["portb_width_code"]
            assert trial["bitstream_parameter_preserved"] is True
