import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_all_request_qualifiers_have_exact_shared_routes_and_types():
    paths = rows("mcu_slave_ahb_request_control_paths.csv")
    cfg = rows("mcu_slave_ahb_request_control_pip_cfg.csv")
    assert len(paths) == 44
    assert len(cfg) == 13
    signals = {row["signal"] for row in paths}
    assert signals == {
        "slave_ahb_hsel", "slave_ahb_hready",
        "slave_ahb_htrans[0]", "slave_ahb_htrans[1]",
        "slave_ahb_hsize[0]", "slave_ahb_hsize[1]", "slave_ahb_hsize[2]",
        "slave_ahb_hburst[0]", "slave_ahb_hburst[1]", "slave_ahb_hburst[2]",
        "slave_ahb_hwrite",
    }
    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(
        encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(
        encoding="utf-8")
    names = [
        "HSEL", "HREADY", "HTRANS0", "HTRANS1", "HSIZE0", "HSIZE1",
        "HSIZE2", "HBURST0", "HBURST1", "HBURST2", "HWRITE",
    ]
    for bit, suffix in enumerate(names, 165):
        name = f"MCU_SLAVE_AHB_{suffix}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims


def test_request_qualifier_smoke_and_evidence_are_narrow():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_request_controls_shared_low_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X14Y12_SLICE0"' in smoke
    assert "INIT(16'h0000)" in smoke
    assert smoke.count(".DOUT(request_low)") == 11
    record = json.loads((ROOT / "qualification" /
                         "mcu_slave_ahb_request_control_route_evidence.jsonl").read_text(
                             encoding="utf-8"))
    assert record["build"] == "pass"
    assert record["hardware"] == "not-run"
    assert record["source_scope"] == "one-shared-safe-low-source"
    assert record["selector_checks"] == 119
    assert record["exact_fields"] == 13
    assert record["routed_pips"] == 13
    assert record["unmapped_pips"] == 0
