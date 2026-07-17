from pathlib import Path
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
    for name in ("ag32_sysctl.h", "ag32_uart.h", "ag32_spi.h", "ag32_i2c.h", "ag32_dma.h"):
        assert (INCLUDE / name).is_file()
