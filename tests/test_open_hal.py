from pathlib import Path
import hashlib
import json
import subprocess

import pytest

from agamemnon.project import find_riscv_tool


ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "agamemnon" / "sdk" / "include"


def test_open_hal_layout_and_api_compile(tmp_path):
    try:
        gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
    except (RuntimeError, OSError) as exc:  # find_riscv_tool raises FileNotFoundError
        pytest.skip(str(exc))
    source = tmp_path / "hal_layout.c"
    source.write_text(r'''
#include <stddef.h>
#include "ag32.h"
_Static_assert(offsetof(ag32_uart_t, FR) == 0x18, "UART FR");
_Static_assert(offsetof(ag32_uart_t, IBRD) == 0x24, "UART IBRD");
_Static_assert(offsetof(ag32_uart_t, DMACR) == 0x48, "UART DMACR");
_Static_assert(offsetof(ag32_i2c_t, CTR) == 0x08, "I2C CTR");
_Static_assert(offsetof(ag32_i2c_t, CR) == 0x10, "I2C CR");
_Static_assert(offsetof(ag32_spi_t, PHASE_CTRL) == 0x10, "SPI phase ctrl");
_Static_assert(offsetof(ag32_spi_t, PHASE_DATA) == 0x30, "SPI phase data");
_Static_assert(offsetof(ag32_dma_t, CONFIG) == 0x30, "DMA config");
_Static_assert(offsetof(ag32_dma_t, CHANNEL) == 0x100, "DMA channels");
_Static_assert(sizeof(ag32_dma_channel_t) == 0x20, "DMA channel stride");
_Static_assert(offsetof(ag32_crc_t, INIT) == 0x10, "CRC initial value");
_Static_assert(offsetof(ag32_crc_t, POL) == 0x14, "CRC polynomial");
_Static_assert(offsetof(ag32_watchdog_t, LOCK) == 0xc00, "watchdog lock");
_Static_assert(AG32_IRQ_GPIO9 == 16, "complete GPIO IRQ table");
_Static_assert(AG32_IRQ_DMAC0_ERROR == 34, "complete DMA IRQ table");
_Static_assert(AG32_IRQ_EXT7 == 44, "complete external IRQ table");
int use_every_driver(void) {
    uint8_t byte = 0;
    uint32_t word = 0;
    int result = ag32_uart_init(AG32_UART0, 62000000u, 115200u);
    result += ag32_uart_putc(AG32_UART0, byte, 1);
    result += ag32_i2c_init(AG32_I2C0, 62000000u, 100000u);
    result += ag32_i2c_read(AG32_I2C0, &byte, 1, 1);
    result += ag32_spi_init(AG32_SPI0, 8);
    result += ag32_spi_write_read(AG32_SPI0, 0x9fu, 1, &word, 3, 1);
    ag32_dma_init();
    result += ag32_dma_copy32(0, &word, &word, 1);
    result += ag32_plic_enable(AG32_IRQ_UART0, 1);
    result += ag32_plic_disable(AG32_IRQ_UART0);
    ag32_crc_configure(AG32_CRC32_POLYNOMIAL, UINT32_MAX, AG32_CRC_POLYSIZE_32);
    result += (int)ag32_crc_result();
    ag32_watchdog_configure(AG32_WATCHDOG0, 1000u, 0);
    ag32_watchdog_feed(AG32_WATCHDOG0);
    ag32_watchdog_disable(AG32_WATCHDOG0);
    return result;
}
''', encoding="utf-8")
    subprocess.run([
        gcc, "-std=c11", "-march=rv32imac", "-mabi=ilp32", "-ffreestanding",
        "-fsyntax-only", "-I", str(INCLUDE), str(source),
    ], check=True, capture_output=True, text=True)


def test_hal_headers_are_packaged_by_configuration():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"sdk/**/*"' in pyproject
    for name in ("ag32_sysctl.h", "ag32_interrupt.h", "ag32_uart.h", "ag32_spi.h", "ag32_i2c.h", "ag32_dma.h", "ag32_crc.h", "ag32_watchdog.h"):
        assert (INCLUDE / name).is_file()


def test_spi_init_uses_apb_reset_without_latching_software_reset():
    header = (INCLUDE / "ag32_spi.h").read_text(encoding="utf-8")
    body = header.split("static inline int ag32_spi_init", 1)[1].split(
        "static inline uint32_t ag32_spi_tx_align", 1
    )[0]
    assert "ag32_apb_reset" in body
    assert "spi->CTRL = AG32_SPI_CTRL_RESET" not in body
    assert "clock_divider & (clock_divider - 1u)" in body


def test_spi_divider_silicon_evidence_covers_documented_domain():
    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "spi_divider_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(item for item in rows
               if item["trial_id"] == "hard-spi0-divider-sweep-20260816")
    observed = row["observed"]
    assert row["result"] == "pass" and row["non_destructive"] is True
    assert observed["dividers"] == [2, 4, 8, 16, 32, 64, 128, 256]
    assert observed["completed_transfers"] == [64] * 8
    assert observed["mtime_ticks"] == sorted(observed["mtime_ticks"])
    assert len(set(observed["mtime_ticks"])) == 8


def test_spi_rx_lane_cleanup_is_silicon_bound():
    header = (INCLUDE / "ag32_spi.h").read_text(encoding="utf-8")
    assert "ag32_spi_rx_value(spi->PHASE_DATA[1], rx_bytes)" in header
    assert "value = (value << 8) | (raw & 0xffu)" in header

    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "hard_peripheral_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(item for item in rows
               if item.get("trial_id") == "hard-spi0-rx-lane-20260816")
    observed = row["observed"]
    assert row["result"] == "pass" and row["non_destructive"] is True
    assert observed["fcb_stat"] == "0x000f0002"
    assert observed["rx_bytes"] == [1, 2, 3, 4]
    assert observed["status"] == [0, 0, 0, 0]
    assert observed["raw_phase_data"] == [
        "0xa50000ff", "0xa500ffff", "0xa5ffffff", "0xffffffff"
    ]

    active = next(item for item in rows
                  if item.get("trial_id") ==
                  "hard-spi0-active-rx-width-matrix-20260816")
    active_observed = active["observed"]
    assert active["result"] == "pass" and active["non_destructive"] is True
    assert active_observed["rx_bytes"] == [1, 2, 3, 4]
    assert active_observed["wire_response_prefix"] == [
        "12", "12 34", "12 34 56", "12 34 56 78"
    ]
    assert active_observed["normalized_api_value"] == [
        "0x00000012", "0x00001234", "0x00123456", "0x12345678"
    ]


def test_uart_baud_silicon_evidence_covers_nominal_matrix():
    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "uart_baud_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(item for item in rows
               if item["trial_id"] == "hard-uart0-nominal-baud-matrix-20260816")
    assert row["result"] == "pass" and row["non_destructive"] is True
    profiles = row["observed"]["profiles"]
    assert [profile["baud"] for profile in profiles] == [9600, 38400, 115200]
    assert [profile["pico_bytes"] for profile in profiles] == ["64/64"] * 3
    assert all(profile["data"] == "ff554100 repeated 16 times"
               for profile in profiles)

    receive = next(item for item in rows
                   if item["trial_id"] ==
                   "hard-uart0-dap-cdc-rx-matrix-20260816")
    assert receive["result"] == "pass" and receive["non_destructive"] is True
    rx_profiles = receive["observed"]["profiles"]
    assert [profile["baud"] for profile in rx_profiles] == [9600, 38400, 115200]
    assert [profile["received"] for profile in rx_profiles] == [64] * 3
    assert [profile["error"] for profile in rx_profiles] == [0] * 3
    assert all(profile["data"] == "ff554100 repeated 16 times"
               for profile in rx_profiles)
    assert "PIN_31" in receive["observed"]["route"]

    runner = (ROOT / receive["runner"]).read_text(encoding="utf-8")
    assert "--execute-sram" in runner
    assert "EXPECTED_FABRIC_SHA256" in runner
    assert '("reset halt", "reset", "shutdown")' in runner
    assert hashlib.sha256((ROOT / receive["runner"]).read_bytes()).hexdigest() == \
        receive["runner_sha256"]
    assert hashlib.sha256((ROOT / receive["example"]).read_bytes()).hexdigest() == \
        receive["source_sha256"]

    duplex = next(item for item in rows
                  if item["trial_id"] ==
                  "hard-uart0-dap-cdc-full-duplex-matrix-20260816")
    assert duplex["result"] == "pass" and duplex["non_destructive"] is True
    assert duplex["observed"]["bytes_each_direction"] == 4096
    duplex_profiles = duplex["observed"]["profiles"]
    assert [profile["baud"] for profile in duplex_profiles] == [
        9600, 38400, 115200]
    assert [profile["target_tx"] for profile in duplex_profiles] == [4096] * 3
    assert [profile["target_rx"] for profile in duplex_profiles] == [4096] * 3
    assert [profile["target_error"] for profile in duplex_profiles] == [0] * 3
    assert [profile["target_mismatch"] for profile in duplex_profiles] == [0] * 3
    assert all(profile["elapsed_s"] < 1.5 * profile["ideal_one_way_s"] + 0.05
               for profile in duplex_profiles)
    assert "PIN_30" in duplex["observed"]["route"]
    assert "PIN_31" in duplex["observed"]["route"]

    duplex_runner = (ROOT / duplex["runner"]).read_text(encoding="utf-8")
    assert "--execute-sram" in duplex_runner
    assert "EXPECTED_FABRIC_SHA256" in duplex_runner
    assert "TRANSFER_BYTES = 4096" in duplex_runner
    assert '("reset halt", "reset", "shutdown")' in duplex_runner
    assert hashlib.sha256((ROOT / duplex["runner"]).read_bytes()).hexdigest() == \
        duplex["runner_sha256"]
    assert hashlib.sha256((ROOT / duplex["example"]).read_bytes()).hexdigest() == \
        duplex["source_sha256"]

    line_rows = [json.loads(line) for line in (
        ROOT / "qualification" / "uart_line_mode_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line]
    line_modes = next(item for item in line_rows
                      if item["trial_id"] ==
                      "hard-uart0-line-modes-parity-control-20260816")
    assert line_modes["result"] == "pass"
    assert line_modes["observed"]["baud"] == 38400
    modes = line_modes["observed"]["modes"]
    assert [mode["mode"] for mode in modes] == ["7E1", "8E1", "8O1", "8N2"]
    assert [mode["target_tx"] for mode in modes] == [256] * 4
    assert [mode["target_rx"] for mode in modes] == [256] * 4
    assert [mode["error"] for mode in modes] == [0] * 4
    assert [mode["mismatch"] for mode in modes] == [0] * 4
    controls = line_modes["observed"]["parity_controls"]
    assert [control["parity_errors"] for control in controls] == [0, 64]
    assert [control["received"] for control in controls] == [64, 64]
    assert all(control["payload_mismatch"] == 0 for control in controls)
    assert all(control["framing_errors"] == 0 for control in controls)
    assert all(control["break_errors"] == 0 for control in controls)
    assert all(control["overrun_errors"] == 0 for control in controls)

    mode_runner = (ROOT / line_modes["runner"]).read_text(encoding="utf-8")
    assert "--execute-sram" in mode_runner
    assert "EXPECTED_FABRIC_SHA256" in mode_runner
    assert "base.cleanup()" in mode_runner
    for field, path_field in (("runner_sha256", "runner"),
                              ("source_sha256", "example"),
                              ("error_source_sha256", "error_example")):
        assert hashlib.sha256((ROOT / line_modes[path_field]).read_bytes()).hexdigest() == \
            line_modes[field]


def test_i2c_terminal_nack_and_active_slave_evidence():
    header = (INCLUDE / "ag32_i2c.h").read_text(encoding="utf-8")
    assert "if (last && result == -3)" in header
    assert "*value = (uint8_t)i2c->RXR" in header

    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "hard_peripheral_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(item for item in rows if item.get("trial_id") ==
               "hard-i2c0-active-slave-write-read-20260816")
    observed = row["observed"]
    assert row["result"] == "pass" and row["non_destructive"] is True
    assert observed["fcb_stat"] == "0x000f0002"
    assert observed["address"] == "0x55"
    assert observed["write_value"] == "0xa6"
    assert [observed[name] for name in (
        "write_address_status", "write_data_status",
        "read_address_status", "read_status",
    )] == [0, 0, 0, 0]
    assert observed["read_value"] == observed["raw_rxr"] == "0x5a"
    assert observed["final_sr"] == "0x81"
    assert observed["pre_fix_read_status"] == -3

    oracle = (ROOT / row["pico_source"]).read_text(encoding="utf-8")
    assert "ADDRESS = 0x55" in oracle
    assert "READ_VALUE = 0x5a" in oracle
    assert "gpio_set_dir(SDA_PIN, GPIO_IN)" in oracle

    repeated = next(item for item in rows if item.get("trial_id") ==
                    "hard-i2c0-repeated-start-multibyte-20260816")
    repeated_observed = repeated["observed"]
    assert repeated["result"] == "pass" and repeated["non_destructive"] is True
    assert repeated_observed["runs"] == 3
    assert repeated_observed["fcb_stat"] == ["0x000f0002"] * 3
    assert repeated_observed["write_values"] == ["0x2a", "0xa6"]
    assert repeated_observed["write_address_status"] == [0, 0, 0]
    assert repeated_observed["write_status"] == [[0, 0]] * 3
    assert repeated_observed["repeated_start_read_address_status"] == [0, 0, 0]
    assert repeated_observed["read_status"] == [[0, 0, 0]] * 3
    assert repeated_observed["read_values"] == [["0x5a", "0xc3", "0x7e"]] * 3
    assert repeated_observed["master_ack_sequence"] == "ACK, ACK, NACK"
    assert repeated_observed["final_sr"] == ["0x81"] * 3

    repeated_oracle = (ROOT / repeated["pico_source"]).read_text(encoding="utf-8")
    assert "W 2A A6, repeated START, R -> 5A C3 7E" in repeated_oracle
    assert "RESPONSE[] = {0x5a, 0xc3, 0x7e}" in repeated_oracle


def test_interrupt_examples_use_packaged_trap_startup_and_compile(tmp_path):
    try:
        gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
    except (RuntimeError, OSError) as exc:
        pytest.skip(str(exc))

    examples = ROOT / "examples" / "riscv_mcu"
    startup = ROOT / "agamemnon" / "sdk" / "startup.S"
    linker = examples / "link_sram.ld"
    for name in ("exception_mailbox", "software_interrupt", "timer_interrupt"):
        output = tmp_path / f"{name}.elf"
        subprocess.run([
            gcc, "-march=rv32imac", "-mabi=ilp32", "-Os",
            "-nostdlib", "-ffreestanding", "-fno-builtin",
            "-ffunction-sections", "-fdata-sections",
            "-I", str(INCLUDE), "-T", str(linker), "-Wl,--gc-sections",
            str(startup), str(examples / f"{name}.c"), "-o", str(output),
        ], check=True, capture_output=True, text=True)
        assert output.is_file()
