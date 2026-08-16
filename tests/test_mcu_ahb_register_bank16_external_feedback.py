"""Pinned contract for the silicon-qualified waited 16-bit AHB scratch."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTED = ROOT / "qualification" / "mcu_ahb_register_bank16_external_feedback_waited_routed.json"
SOURCE = ROOT / "qualification" / "mcu_ahb_register_bank16_external_feedback_waited.v"
LEDGER = ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl"


def cells():
    design = json.loads(ROUTED.read_text(encoding="utf-8"))
    return next(iter(design["modules"].values()))["cells"]


def test_waited_bank_has_sixteen_state_and_external_feedback_cells():
    table = cells()
    captures = [table["capture%d" % lane] for lane in range(16)]
    feedback = [table["feedback_buffer%d" % lane] for lane in range(16)]
    assert all(cell["type"] == "GENERIC_SLICE" for cell in captures + feedback)
    assert len({cell["attributes"]["NEXTPNR_BEL"] for cell in captures + feedback}) == 32
    assert all("agamemnon_direct_d_feedback" not in cell.get("attributes", {})
               for cell in captures + feedback)


def test_lane12_moves_around_the_qualified_wait_controller():
    table = cells()
    posted_design = json.loads(
        (ROOT / "qualification" / "mcu_ahb_posted_capture16_routed.json")
        .read_text(encoding="utf-8"))
    posted = next(iter(posted_design["modules"].values()))["cells"]
    for lane in range(16):
        if lane != 12:
            assert table["capture%d" % lane]["attributes"]["NEXTPNR_BEL"] == \
                posted["capture%d" % lane]["attributes"]["NEXTPNR_BEL"]
    assert table["write_wait_stage"]["attributes"]["NEXTPNR_BEL"] == "X14Y11_SLICE6"
    assert table["capture12"]["attributes"]["NEXTPNR_BEL"] == "X14Y10_SLICE6"


def test_all_sixteen_exact_hrdata_endpoints_survive_routing():
    table = cells()
    endpoint = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 23, 24, 25, 26, 27, 28]
    for lane, dout in enumerate(endpoint):
        cell = table["mcu_h%d" % lane]
        assert cell["type"] == "MCU_DOUT"
        assert cell["attributes"]["NEXTPNR_BEL"] == "X10Y5_MCU_DOUT%d" % dout


def test_source_requires_the_waited_data_phase_and_external_feedback():
    source = SOURCE.read_text(encoding="utf-8")
    assert ".INIT(16'h0080)" in source
    assert ".INIT(16'hDDDD)" in source
    assert source.count(".INIT(16'h0B08)") == 16
    assert source.count(".INIT(16'hAAAA)") == 16
    assert "agamemnon_direct_d_feedback" not in source


def test_silicon_ledger_records_retention_not_just_posted_capture():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record = next(row for row in records if row.get("trial_id") ==
                  "mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815")
    assert record["result"] == "pass_retained_16_bit_scratch"
    assert "immediate=0, poison=0 and repeat=0" in record["observed"]
    assert "arbitrary widths" in record["scope"]
