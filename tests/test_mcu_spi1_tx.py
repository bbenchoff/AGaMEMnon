import csv
from collections import defaultdict
from pathlib import Path

from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_spi1_tx_six_lane_composition_is_exact_and_l48_only():
    paths = rows("mcu_spi1_tx_l48_paths.csv")
    cfg = rows("mcu_spi1_tx_l48_pip_cfg.csv")
    assert len(paths) == 52
    assert len(cfg) == 40

    expected = {
        "spi1_sck_data": ("X10Y5_BufMUX04", "X20Y13_IOMUX03"),
        "spi1_sck_oe": ("X9Y5_BufMUX00", "X20Y13_IOMUX07"),
        "spi1_csn_data": ("X9Y5_BufMUX01", "X19Y13_IOMUX03"),
        "spi1_csn_oe": ("X9Y5_BufMUX09", "X19Y13_IOMUX07"),
        "spi1_mosi_data": ("X13Y7_BufMUX12", "X19Y13_IOMUX02"),
        "spi1_mosi_oe": ("X13Y6_BufMUX00", "X19Y13_IOMUX06"),
    }
    by_signal = defaultdict(list)
    for row in paths:
        by_signal[row["signal"]].append(row)
        assert row["evidence"] == \
            "vendor-spi1-tx-eight-root-agreement-structural6987-composition"
    assert set(by_signal) == set(expected)
    all_edges = []
    for signal, lane in by_signal.items():
        lane.sort(key=lambda row: int(row["step"]))
        assert [int(row["step"]) for row in lane] == list(range(len(lane)))
        assert lane[0]["src_wire"] == expected[signal][0]
        assert lane[-1]["dst_wire"] == expected[signal][1]
        assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(lane, lane[1:]))
        all_edges.extend((row["src_wire"], row["dst_wire"]) for row in lane)
    assert len(all_edges) == len(set(all_edges)) == 52

    path_edges = set(all_edges)
    cfg_edges = {(row["src_wire"], row["dst_wire"]) for row in cfg}
    assert cfg_edges <= path_edges
    for row in cfg:
        clears = [int(value) for value in row["clear_selectors"].split(";") if value]
        sets = [int(value) for value in row["set_selectors"].split(";") if value]
        if row["cell_table"] == "fabric":
            assert len(clears) == 10
            assert clears == list(range(clears[0], clears[0] + 10))
            assert len(sets) == 2
            assert set(sets) <= set(clears)
        else:
            assert row["cell_table"] == "mcu"
            assert clears == [0]
            assert sets in ([], [0])
    for edge in path_edges - cfg_edges:
        assert "Y13_RMUX" in edge[1] or "Y13_IOMUX" in edge[1]

    first_hops = mcu_entry_first_hops(CHIPDB)
    for lane in by_signal.values():
        root = lane[0]["src_wire"]
        assert first_hops[root] == frozenset({lane[0]["dst_wire"]})

    padfeeds = rows("padfeed_L48_top.csv")
    pin12_spi1 = next(
        row for row in padfeeds
        if row["padtile_x"] == "20" and row["padtile_y"] == "13"
        and row["iomux_z"] == "3" and row["padfeed_rmux"] == "16"
        and row["src_res"] == "RMUX85" and row["src_x"] == "20"
        and row["src_y"] == "9"
    )
    assert pin12_spi1["cfg_group"] == "CFG_RMUX2"
    assert pin12_spi1["codeword_sels"] == "0,4"
    assert pin12_spi1["codeword_bytes"] == "403,519"
    assert pin12_spi1["codeword_masks"] == "2,1"


def test_spi1_tx_typed_roots_and_atomic_lock_are_registered():
    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(encoding="utf-8")
    modules = (
        "MCU_SPI1_SCK_DATA", "MCU_SPI1_SCK_OE",
        "MCU_SPI1_CSN_DATA", "MCU_SPI1_CSN_OE",
        "MCU_SPI1_MOSI_DATA", "MCU_SPI1_MOSI_OE",
    )
    for bit, module in enumerate(modules, 273):
        assert f'{bit}: "{module}"' in arch
        assert f"module {module}" in prims
        assert f'"{module}"' in packer
    assert '"mcu_spi1_tx_l48_paths.csv"' in gpio
    assert '"mcu_spi1_tx_l48_pip_cfg.csv"' in gpio
    assert "lock_spi1_tx_corridors(ctx)" in packer
    for bel in ("X20Y13_OEPAD3", "X19Y13_OEPAD3", "X19Y13_OEPAD2"):
        assert f'"{bel}"' in packer
