# RISC-V firmware stubs

These freestanding RV32 programs run at `0x20000000` and exercise the fabric
from the AG32 MCU. They use no C library or runtime.

## Build

```bash
riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os \
  -nostdlib -ffreestanding -T examples/firmware/link.ld \
  -o looptest.elf examples/firmware/looptest.c
riscv64-unknown-elf-objcopy -O binary looptest.elf looptest.bin
```

Run firmware with an uncompressed fabric image:

```bash
agamemnon sram looptest.bin --fabric loop.bin
```

Build the clock/configuration stub used by the physical-pin examples:

```bash
mkdir -p .tmp
riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os \
  -nostdlib -ffreestanding -T examples/firmware/link.ld \
  -o .tmp/clkcfg_stub.elf examples/firmware/clkcfg_stub.c
riscv64-unknown-elf-objcopy -O binary \
  .tmp/clkcfg_stub.elf .tmp/clkcfg_stub.bin
```

## Files

| File | Function |
|---|---|
| `clkcfg_stub.c` | selects HSI for FCB streaming, enables required clocks, configures the fabric, waits for the selected PLL, and restores it |
| `looptest.c`, `looptest4.c`, `looptest8.c` | drive MCU GPIO into fabric loopback paths and store returned values |
| `dout_read_stub.c` | reads a fabric value through the MCU data-return path |
| `ahb_test.c` | writes and reads the External-AHB fabric window at `0x60000000` |
| `ahb_blink.c` | repeatedly writes the External-AHB window for a CPU-controlled output demo |

The SRAM loader places the fabric image at `0x20002000`; the stubs store result
words at `0x20001000`.

## Loopback

```bash
agamemnon build examples/designs/mcu_loop2.v --uarch --mcu --research-unsafe -o loop.bin
agamemnon sram looptest.bin --fabric loop.bin
```

The generic `--mcu` bridge option is not release-qualified, so release-strict
rejects the build before synthesis; `--research-unsafe` is required and the
image carries a provenance sidecar.

The expected result is `FCB STAT = 0x000f0002` followed by complementary
`din`/`dout` values.

## Register summary

- GPIO4 base: `0x40018000`
- APB clock enable: `0x03000060`
- FCB base: `0x40010000`
- External-AHB fabric window: `0x60000000`

Definitions are in `mcu/ag32.h`.
