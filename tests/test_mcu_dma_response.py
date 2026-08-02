import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_dma_response_all_channels_are_exact_and_typed():
    paths = rows("mcu_dma_response_all_paths.csv")
    assert len(paths) == 26
    assert len(rows("mcu_dma_response_all_pip_cfg.csv")) == 26
    assert {row["signal"] for row in paths} == {
        f"ext_dma_DMAC{kind}[{bit}]"
        for kind in ("CLR", "TC") for bit in range(4)
    }
    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" /
              "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for kind in ("CLR", "TC"):
        for bit in range(4):
            assert f"module MCU_DMA_{kind}{bit}" in prims
    assert '"mcu_dma_response_all_paths.csv"' in arch
    assert '"mcu_dma_response_all_pip_cfg.csv"' in bitgen


def test_dma_response_smoke_uses_four_recovered_lut_pairs():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_dma_response_all_route_smoke.v").read_text(encoding="utf-8")
    for bit, slice_index in enumerate((8, 12, 4, 2)):
        assert f'BEL="X1Y4_SLICE{slice_index}"' in smoke
        assert f".I({{dma_clear{bit}, dma_tc{bit}, 2'b00}})" in smoke


def test_dma_response_evidence_is_route_only():
    evidence = ROOT / "qualification" / "mcu_dma_response_route_evidence.jsonl"
    records = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    record = records[-1]
    assert record["build"] == "pass"
    assert record["source_scope"] == "eight-independent-response-sources-four-lut-pairs"
    assert record["exact_fields"] == 26
    assert record["selector_checks"] == 204
    assert record["routed_pips"] == 26
    assert record["unmapped_pips"] == 0
    assert record["hardware"] == "not-run"
