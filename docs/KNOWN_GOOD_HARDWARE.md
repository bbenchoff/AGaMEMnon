# Known-good hardware

Last updated: 2026-07-16

This table records combinations actually used by AGaMEMnon. “Known good” does
not broaden the feature-level claims in [STATUS.md](STATUS.md).

## Reference board

| Field | Qualified value |
|---|---|
| Board | AGM AG32VF303 LQFP-48 development board |
| MCU marking | `AG32VF303CCT6` |
| Fabric target | `AGRV2KL48` |
| Device ID | `0x40200001` |
| RISC-V `misa` | `0x40801125` (`RV32IMAFC`) |
| Main flash | 256 KiB |
| SRAM | 128 KiB |
| Qualified HSE | 8 MHz |
| Board revision | Not identified on the qualification fixture |

If a board carries another marking or package, report it as a new hardware
target rather than selecting this board definition by visual similarity.

## Transports

| Transport combination | State | Boundary |
|---|---|---|
| AGM CMSIS-DAP + compatible AGM `riscv -dap` OpenOCD | Silicon-qualified | Probe, volatile MCU/fabric SRAM load, complete flash backup, sector program, and readback |
| Target USB + flash-resident uploader 2.1 (`cafe:4001`) | Silicon-qualified | Identify, read, page erase, write, verify, `GO`, and reset; not factory-installed and not recovery |
| Raspberry Pi Pico 2 USB bridge firmware | Host/Pico tested | Pico protocol and USB enumeration tested; target UART link awaits the documented five-wire addition |

Stock upstream and OSS CAD Suite OpenOCD are not known-good substitutes for
the DAP row because they lack AGM's target extension.

## Qualification fixture wiring

| AG32 L48 pin | Pico pin | Use |
|---|---|---|
| `PIN_25` | GP12 | Fabric output observation |
| `PIN_26` | GP13 | Fabric output observation |
| `PIN_27` | GP16 | Fabric output observation |
| `PIN_28` | GP17 | Fabric output observation |

The separate UART recovery modification is defined in
[UART_BOOTLOADER.md](UART_BOOTLOADER.md). Do not infer it from this four-output
qualification harness.

## Host/tool pins

The intended reproducible tool versions are stored in
[`tools/bundle/manifest.json`](../tools/bundle/manifest.json), including OSS
CAD Suite date, nextpnr commit, RISC-V toolchain commit, and external
PlatformIO framework commits.

Compatible OpenOCD is intentionally not assigned a redistributable “known-good
release” entry until the binary can be paired with its exact patched GPL
source. Local AGM-capable binaries can be tested with `agamemnon doctor`, but
their presence alone is not a release provenance claim.

## Adding a combination

Use the hardware-qualification issue form and include the device marking,
board revision, transport, wiring, host OS, tool versions, source/artifact
hashes, observable oracle, and restoration result. Accepted qualification data
belongs in the append-only records under `qualification/`.
