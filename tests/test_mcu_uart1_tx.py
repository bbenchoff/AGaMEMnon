import csv
from pathlib import Path

from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_uart1_tx_boundary_is_exact_typed_and_l48_only():
    paths = rows("mcu_uart1_tx_l48_paths.csv")
    cfg = rows("mcu_uart1_tx_l48_pip_cfg.csv")
    padfeed = rows("padfeed_L48_top.csv")
    oepad = rows("physical_uart1_oe_L48.csv")
    assert len(paths) == 21
    assert len(cfg) == 17
    assert {row["signal"] for row in paths} == {
        "uart1_txd_data", "uart1_txd_oe"
    }
    data = [row for row in paths if row["signal"] == "uart1_txd_data"]
    enable = [row for row in paths if row["signal"] == "uart1_txd_oe"]
    assert data[0]["src_wire"] == "X5Y5_BufMUX04"
    assert data[0]["dst_wire"] == "X5Y5_InputMUX05"
    assert [(row["src_wire"], row["dst_wire"]) for row in data][-2:] == [
        ("X20Y9_RMUX19", "X20Y13_RMUX24"),
        ("X20Y13_RMUX24", "X20Y13_IOMUX01"),
    ]
    assert enable[0]["src_wire"] == "X4Y5_BufMUX00"
    assert enable[0]["dst_wire"] == "X4Y5_InputMUX01"
    assert [(row["src_wire"], row["dst_wire"]) for row in enable][-2:] == [
        ("X20Y9_RMUX25", "X20Y13_RMUX00"),
        ("X20Y13_RMUX00", "X20Y13_IOMUX05"),
    ]
    assert cfg[0]["set_selectors"] == ""
    assert cfg[1]["set_selectors"] == "23;29"
    exact_feed = {
        (row["padfeed_rmux"], row["src_res"], row["src_x"], row["src_y"]): row
        for row in padfeed
        if row["padtile_x"] == "20" and row["padtile_y"] == "13"
        and row["iomux_z"] == "1"
    }
    assert exact_feed[("24", "RMUX19", "20", "9")]["cfg_group"] == "CFG_RMUX3"
    assert exact_feed[("24", "RMUX19", "20", "9")]["codeword_sels"] == "0,4"
    assert exact_feed[("0", "RMUX25", "20", "9")]["codeword_sels"] == "0,4"
    assert oepad == [{
        "pin": "PIN_10", "x": "20", "y": "13", "z": "1",
        "data_iomux": "1", "data_rmux": "24",
        "oe_iomux": "5", "oe_rmux": "0",
        "cfg_x": "19", "cfg_y": "13", "oe_cfg": "CFG_IOMUX0",
        "oe_sels": "35;39", "clear_scope": "full_field",
        "companion_sets": "CFG_IOMUX1:27;CFG_IOMUX2:13",
        "companion_clears": "CFG_IOMUX3:6;CFG_IOMUX3:34",
        "qualification": "vendor-uart1-eight-seed-route-pico-silicon-20260824",
    }]

    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(
        encoding="utf-8"
    )
    assert '292: "MCU_UART1_TXD_DATA"' in arch
    assert '293: "MCU_UART1_TXD_OE"' in arch
    assert '"mcu_uart1_tx_l48_paths.csv"' in gpio
    assert '"mcu_uart1_tx_l48_pip_cfg.csv"' in gpio
    for module in ("MCU_UART1_TXD_DATA", "MCU_UART1_TXD_OE"):
        assert f"module {module}" in prims
    assert 'candidate->type == ctx->id(prefix + "TXD_DATA")' in packer
    assert 'candidate->type == ctx->id(prefix + "TXD_OE")' in packer
    assert "lock_uart_tx_corridors(ctx)" in packer
    assert "mixed UART controller typed composition is not characterized" in packer

    first_hops = mcu_entry_first_hops(CHIPDB)
    assert first_hops["X5Y5_BufMUX04"] == frozenset({"X5Y5_InputMUX05"})
    assert first_hops["X4Y5_BufMUX00"] == frozenset({"X4Y5_InputMUX01"})
