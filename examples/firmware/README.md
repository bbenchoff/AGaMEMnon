# RISC-V firmware stubs

Small freestanding RISC-V programs for the AG32 core, loaded to SRAM over SWD (or flashed) to exercise
the fabric from the MCU side. Each is a single `.c` with a `_start` at `0x20000000`; no libc, no runtime.

## Build

Any `riscv64-unknown-elf-gcc` + the SRAM linker script here:

```bash
riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os -nostdlib -ffreestanding \
    -T link.ld -o looptest.elf looptest.c
riscv64-unknown-elf-objcopy -O binary looptest.elf looptest.bin
```

Load + run a fabric image + a firmware stub together (volatile, touches no flash):

```bash
agamemnon sram looptest.bin -b loop.bin        # fabric @0x20002000, firmware @0x20000000, resume
```

## The stubs

| file | what it does |
|---|---|
| `clkcfg_stub.c` | switch to HSI, enable the FCB + GPIO clocks, `FCB_AutoConfig` a fabric image from `0x20002000`. The config prelude every other stub starts with. |
| `looptest.c` / `looptest4.c` / `looptest8.c` | the MCU↔fabric **GPIO loopback**: drive GPIO4 output bits into the fabric, read the fabric's reply on GPIO4 input bits. `dout = ~din` on all combinations = the fabric LUT computes and the MCU observes it. |
| `dout_read_stub.c` | read a fabric value back on GPIO4 (the `hrdata`/dout readback path). |
| `ahb_test.c` | **AHB write/read**: `*(u32*)0x60000000 = v` → the fabric captures it; read it back. |
| `ahb_blink.c` | **CPU-controlled pin blink**: after configuring the fabric, write `0`/`1` to `0x60000000` in a loop. With the `ahb_pad` fabric design (`../designs/ahb_pad.v`), the captured register drives `PIN_18`, so the pin blinks at the rate the loop sets (~1.25 Hz). |

## Loopback demo (open flow, silicon-proven)

The loopback fabric image now builds through the open toolchain (no vendor binary):

```bash
agamemnon build ../designs/mcu_loop2.v --mcu -o loop.bin   # yosys → nextpnr-generic → bitgen
agamemnon sram looptest.bin -b loop.bin                    # load + run
# results land at 0x20001000: STAT=0x000f0002 (fabric ACTIVE), then dout = ~din for each input
```

On real silicon: `STAT = 0x000f0002`; `din=0 → dout=1`, `din=1 → dout=0` — the fabric inverts and the MCU
reads it back, across all input combinations. See `../loopback/` for the flagship readback demo and
`docs/HARDWARE_VALIDATION.md` for the full silicon log.

## Register reference

GPIO4 @ `0x40018000` (DIR `+0x400`, AFSEL `+0x420`, masked DATA at `base + (mask<<2)`);
APB clock-enable @ `0x03000060` (FCB = bit 0, GPIO4 = bit 8); FCB @ `0x40010000` (CTRL/AUTO/STAT);
External-AHB fabric slave @ `0x60000000`. Full map: `../../mcu/ag32.h`.
