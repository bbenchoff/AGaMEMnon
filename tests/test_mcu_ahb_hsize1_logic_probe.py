"""Pinned contract for the silicon-qualified HSIZE[1] logic corridor."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ROUTED = ROOT / "qualification" / "mcu_ahb_hsize1_logic_probe_routed.json"
LEDGER = ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def routed_top():
    return json.loads(ROUTED.read_text(encoding="utf-8"))["modules"]["top"]


def test_hsize1_logic_corridor_and_codewords_are_exact():
    paths = rows("mcu_hsize1_logic_paths.csv")
    fields = rows("mcu_hsize1_logic_pip_cfg.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y12_BufMUX04", "X13Y12_InputMUX05"),
        ("X13Y12_InputMUX05", "X14Y12_RMUX34"),
        ("X14Y12_RMUX34", "X14Y12_IMUX14"),
    ]
    assert [
        (row["src_wire"], row["dst_wire"], row["cell_table"], row["cfg_group"],
         row["clear_selectors"], row["set_selectors"])
        for row in fields
    ] == [
        ("X13Y12_BufMUX04", "X13Y12_InputMUX05", "mcu", "InputMUX5", "0", ""),
        ("X13Y12_InputMUX05", "X14Y12_RMUX34", "fabric", "CFG_RMUX5",
         "40;41;42;43;44;45;46;47;48;49", "42;48"),
        ("X14Y12_RMUX34", "X14Y12_IMUX14", "fabric", "CFG_IMUX3",
         "24;25;26;27;28;29;30;31;32;33;34;35", "31;34"),
    ]


def test_retained_probe_uses_vendor_route_and_identity_lut():
    top = routed_top()
    cell = top["cells"]["hsize1_identity"]
    assert cell["attributes"]["NEXTPNR_BEL"] == "X14Y12_SLICE3"
    assert int(cell["parameters"]["INIT"], 2) == 0xF0F0
    route = top["netnames"]["hsize1"]["attributes"]["ROUTING"]
    for edge in (
        "X13Y12_BufMUX04.X13Y12_InputMUX05",
        "X13Y12_InputMUX05.X14Y12_RMUX34",
        "X14Y12_RMUX34.X14Y12_IMUX14",
    ):
        assert edge in route


def test_evidence_records_selector_ablation_and_narrow_scope():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record = next(row for row in records if row.get("trial_id") ==
                  "mcu-ahb-hsize1-logic-route-silicon-20260815")
    assert record["result"] == "pass_hsize1_logic_route"
    assert "half_errors=256" in record["observed"]
    assert "CFG_RMUX5 {43,49}" in record["observed"]
    assert "does not qualify byte strobes" in record["scope"]


def test_engine_registers_hsize1_tables_as_architecture_and_exact_fields():
    source = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(
        encoding="utf-8")
    assert '"mcu_hsize1_logic_paths.csv"' in source
    assert '"mcu_hsize1_logic_pip_cfg.csv"' in source
    assert "qualified request-control oracle hop(s)" in source
