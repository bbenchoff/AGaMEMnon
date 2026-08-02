import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_x9_haddr_corridor_and_fields_are_complete():
    paths = rows("bram_x9_haddr_paths.csv")
    fields = rows("bram_x9_haddr_pip_cfg.csv")
    assert len(paths) == 21
    assert len(fields) == 21
    assert {int(row["logical_bit"]) for row in paths} == {2, 3, 4, 5}
    assert paths[0]["src_wire"] == "X13Y12_BufMUX12"
    assert paths[-1]["dst_wire"] == "X13Y4_IMUX06"
    assert {(row["src_wire"], row["dst_wire"]) for row in paths} == {
        (row["src_wire"], row["dst_wire"]) for row in fields
    }
    assert all(len(row["set_selectors"].split(";")) == 2 for row in fields)


def test_x9_haddr_tables_are_consumed_by_arch_and_bitgen():
    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(encoding="utf-8")
    assert '"bram_x9_haddr_paths.csv"' in arch
    assert '"bram_x9_haddr_pip_cfg.csv"' in bitgen


def test_memory_libmap_address_alignment_is_preserved_for_narrow_modes():
    mapping = (ROOT / "agamemnon" / "synth" / "ag32_brams_map.v").read_text(
        encoding="utf-8"
    )
    # memory_libmap aligns a x9 word index in PORT_*_ADDR[12:3].  Re-slicing
    # [9:0] and appending 3'b111 shifts it a second time and connects logical
    # address bit zero to physical Address[6] instead of Address[3].
    assert "{PORT_A_ADDR[12:3], 3'b111}" in mapping
    assert "{PORT_B_ADDR[12:3], 3'b111}" in mapping
    assert "{PORT_A_ADDR[9:0], 3'b111}" not in mapping
