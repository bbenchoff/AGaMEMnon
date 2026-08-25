import csv
from collections import defaultdict
from pathlib import Path

from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_spi0_tx_six_lane_composition_is_exact_and_l48_only():
    paths = rows("mcu_spi0_tx_l48_paths.csv")
    cfg = rows("mcu_spi0_tx_l48_pip_cfg.csv")
    assert len(paths) == 51
    assert len(cfg) == 39

    expected = {
        "spi0_sck_data": ("X10Y5_BufMUX02", "X20Y13_IOMUX03"),
        "spi0_sck_oe": ("X10Y5_BufMUX10", "X20Y13_IOMUX07"),
        "spi0_csn_data": ("X10Y5_BufMUX03", "X19Y13_IOMUX03"),
        "spi0_csn_oe": ("X10Y5_BufMUX11", "X19Y13_IOMUX07"),
        "spi0_mosi_data": ("X13Y7_BufMUX08", "X19Y13_IOMUX02"),
        "spi0_mosi_oe": ("X13Y7_BufMUX16", "X19Y13_IOMUX06"),
    }
    by_signal = defaultdict(list)
    for row in paths:
        by_signal[row["signal"]].append(row)
        assert row["evidence"] == \
            "vendor-spi0-tx-eight-root-agreement-structural6907-composition"
    assert set(by_signal) == set(expected)
    for signal, lane in by_signal.items():
        lane.sort(key=lambda row: int(row["step"]))
        assert [int(row["step"]) for row in lane] == list(range(len(lane)))
        assert lane[0]["src_wire"] == expected[signal][0]
        assert lane[-1]["dst_wire"] == expected[signal][1]
        assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(lane, lane[1:]))

    path_edges = {(row["src_wire"], row["dst_wire"]) for row in paths}
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
    for signal, lane in by_signal.items():
        root = lane[0]["src_wire"]
        assert first_hops[root] == frozenset({lane[0]["dst_wire"]})


def test_spi0_tx_physical_terminals_and_typed_lock_are_bound():
    oepads = {row["pin"]: row for row in rows("physical_oepad_L48.csv")}
    expected = {
        "PIN_12": ("20", "13", "3", "0", "7", "20", "8;12"),
        "PIN_13": ("19", "13", "3", "0", "7", "12", "10;11"),
        "PIN_14": ("19", "13", "2", "8", "6", "20", "1;5"),
    }
    for pin, values in expected.items():
        row = oepads[pin]
        assert (row["x"], row["y"], row["data_iomux"], row["data_rmux"],
                row["oe_iomux"], row["oe_rmux"], row["oe_sels"]) == values
        assert row["clear_scope"] == "selector_group"
        assert row["qualification"] == \
            "vendor-spi0-tx-eight-root-agreement-structural6907-composition"
    assert oepads["PIN_12"]["companion_sets"] == \
        "CFG_IOMUX1:41;CFG_IOMUX2:27;CFG_IOMUX3:13;CFG_IOMUX3:41"

    padfeeds = rows("padfeed_L48_top.csv")
    required = {
        ("20", "13", "7", "20", "RMUX39", "20", "9"): ("", "", ""),
        ("19", "13", "3", "0", "RMUX25", "19", "9"): ("0,4", "409,525", "64,32"),
        ("19", "13", "7", "12", "RMUX09", "19", "9"): ("25,27", "2612,2496", "32,8"),
        ("19", "13", "2", "8", "RMUX55", "19", "9"): ("0,4", "409,524", "128,1"),
        ("19", "13", "6", "20", "RMUX62", "19", "9"): ("25,27", "2612,2496", "32,8"),
    }
    indexed = {
        (row["padtile_x"], row["padtile_y"], row["iomux_z"],
         row["padfeed_rmux"], row["src_res"], row["src_x"], row["src_y"]):
        (row["codeword_sels"], row["codeword_bytes"], row["codeword_masks"])
        for row in padfeeds
    }
    for key, codeword in required.items():
        assert indexed[key] == codeword

    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(encoding="utf-8")
    modules = (
        "MCU_SPI0_SCK_DATA", "MCU_SPI0_SCK_OE",
        "MCU_SPI0_CSN_DATA", "MCU_SPI0_CSN_OE",
        "MCU_SPI0_MOSI_DATA", "MCU_SPI0_MOSI_OE",
    )
    for bit, module in enumerate(modules, 266):
        assert f'{bit}: "{module}"' in arch
        assert f"module {module}" in prims
        assert f'"{module}"' in packer
    assert '"mcu_spi0_tx_l48_paths.csv"' in gpio
    assert '"mcu_spi0_tx_l48_pip_cfg.csv"' in gpio
    assert "lock_spi0_tx_corridors(ctx)" in packer
    for bel in ("X20Y13_OEPAD3", "X19Y13_OEPAD3", "X19Y13_OEPAD2"):
        assert f'"{bel}"' in packer
