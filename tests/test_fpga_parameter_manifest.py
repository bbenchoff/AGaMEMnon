import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "agamemnon" / "chipdb" / "agrv2k_parameter_manifest.json"


def test_agrv2k_parameter_manifest_is_complete_and_non_claiming():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["device"] == "AGRV2K"
    assert data["status"] == "declaration-complete-candidate-domain-partial"
    assert data["summary"] == {
        "site_present_families": 6,
        "parameter_declarations": 136,
        "placement_parameters": 18,
        "architecture_parameters": 118,
        "known_legal_domains": 3,
        "candidate_domains": 2,
        "open_flow_bounded_domains": 5,
    }
    assert "do not establish legal values" in data["non_claim"]


def test_bram_width_candidate_domain_keeps_claim_boundaries():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    primitives = {row["primitive"]: row for row in data["primitives"]}
    assert set(primitives) == {
        "alta_pllve", "alta_rio", "alta_slice", "alta_bram9k",
        "alta_io_gclk", "alta_rv32",
    }
    bram = {row["name"]: row for row in primitives["alta_bram9k"]["parameters"]}
    assert bram["INIT_VAL"]["default"] == "9216'b0"
    assert bram["PORTA_WIDTH"]["legal_values"] is None
    assert bram["PORTA_WIDTH"]["candidate_values"] == [
        "00000", "01000", "01100", "01110", "01111", "10000"
    ]
    assert bram["PORTA_WIDTH"]["open_flow_supported_values"] == [
        "00000", "01000", "01100", "01110", "01111"
    ]
    assert bram["PORTA_WIDTH"]["backend_acceptance_state"] == (
        "accepts-candidates-and-invalid-negative-control"
    )
    assert bram["PORTB_WIDTH"]["backend_acceptance_state"] == (
        "accepts-candidates-and-invalid-negative-control"
    )
    rio = {row["name"]: row for row in primitives["alta_rio"]["parameters"]}
    drive = rio["CFG_PDRCTRL"]
    assert drive["legal_values"] == [f"{code:04b}" for code in range(1, 16)]
    assert drive["semantic_domain"] == {
        "current_ma": list(range(2, 31, 2)),
        "mapping": "CFG_PDRCTRL = current_mA / 2",
    }
    assert drive["backend_acceptance_state"] == "accepts-full-documented-domain"
    assert drive["open_flow_supported_values"] == []
    assert drive["behavior_state"] == "electrical-unqualified"
    for name in ("CFG_PULL_UP", "CFG_OPEN_DRAIN"):
        field = rio[name]
        assert field["legal_values"] == ["0", "1"]
        assert field["backend_acceptance_state"] == "accepts-both-isolated-values"
        assert field["encoding_state"] == "per-pad-signatures-no-general-formula"
        assert field["open_flow_supported_values"] == []
        assert field["behavior_state"] == "electrical-unqualified"
    assert rio["CFG_SLR"]["legal_values"] is None
