import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_dma_request_all_channels_shared_tree_is_exact_and_typed():
    paths = rows("mcu_dma_request_all_paths.csv")
    assert len(paths) == 128
    assert len(rows("mcu_dma_request_all_pip_cfg.csv")) == 23
    assert {row["signal"] for row in paths} == {
        f"ext_dma_DMAC{kind}REQ[{bit}]"
        for kind in ("B", "LB", "S", "LS")
        for bit in range(4)
    }
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" /
              "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for kind in ("BREQ", "LBREQ", "SREQ", "LSREQ"):
        for bit in range(4):
            assert f"module MCU_DMA_{kind}{bit}" in prims
    assert '"mcu_dma_request_all_paths.csv"' in arch
    assert '"mcu_dma_request_all_pip_cfg.csv"' in bitgen


def test_dma_request_smoke_is_shared_and_safe_low():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_dma_request_all_shared_low_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X14Y12_SLICE0"' in smoke
    assert "INIT(16'h0000)" in smoke
    assert smoke.count(".DOUT(dma_request_low)") == 16


def test_dma_request_evidence_is_narrow_and_reproducible():
    evidence = ROOT / "qualification" / "mcu_dma_request_route_evidence.jsonl"
    records = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    record = records[-1]
    assert record["build"] == "pass"
    assert record["source_scope"] == "one-shared-safe-low-source-all-16-endpoints"
    assert record["exact_fields"] == 23
    assert record["selector_checks"] == 214
    assert record["routed_pips"] == 39
    assert record["unmapped_pips"] == 0
    assert record["hardware"] == "not-run"
