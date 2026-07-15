# AGaMEMnon

AGaMEMnon is an open synthesis, place-and-route, bitstream, and programming
toolchain for the AGM AG32 / AGRV2K embedded FPGA fabric. It targets the
2,112-LUT fabric integrated beside the AG32 RV32IMAFC microcontroller.

```text
synthesizable Verilog
  -> Yosys
  -> nextpnr-generic --uarch agrv2k
  -> AGaMEMnon bitgen
  -> SRAM or flash image
```

The release flow does not invoke Supra, `af.exe`, Quartus, or a vendor-routed
checkpoint. It also supports lossless bitstream inspection and editing,
routed-netlist verification, SRAM configuration, and main-flash programming.

## Supported feature set

| Area | Support |
|---|---|
| RTL | Combinational and sequential Verilog, LUT4s, flip-flops, counters, shifts, state machines, constants, and global fabric clocks |
| Place and route | nextpnr Viaduct backend with regional placement, fanout splitting, strict selector encoding, conservative timing, and fail-closed unsupported routes |
| Physical IO | AGRV2KL48 bond map; qualified inputs on PIN_10, PIN_11, PIN_15, and PIN_19; qualified header outputs and PIN_25 through PIN_28 |
| MCU bridge | Four-bit GPIO loopback, simultaneous 32-bit External-AHB reads, and protocol-valid writes covering all 32 write-data lanes in four-bit groups |
| Dedicated carry | Opt-in same-tile chains and one qualified 33-site corridor supporting a seed plus 32 arithmetic stages |
| BRAM | Inference and routing for an integrated `ALTA_BRAM9K`; one x18 Port-A path and one x2 Port-B read/control path are silicon-qualified |
| PLL | `(SYSCLK,HSE)` pairs `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz |
| Timing | Fail-closed frequency target using conservative cell arcs and worst delay per driving mux family |
| Bitstreams | LZW `.bin`, raw image, CRC-32/BZIP2, LUT editing, and lossless named `.agasc` conversion |
| Programming | SWD probe, volatile SRAM configuration, full-flash backup, main-flash erase/program/readback verification, and boot from an existing compressed-config pointer |

Release routing accepts only conflict-free physical selector encodings or
tile-relative encodings for which every observation agrees. A route that
requires a predicted, conflicting, legacy, or unresolved selector is rejected
before an output image is retained.

## Support boundary

The following are outside the supported feature set:

- carry spill outside the qualified 33-site corridor, multiple long carry
  chains, branched carry, and malformed chains;
- general BRAM placement across every tile, width, initialization layout,
  write/collision mode, and arbitrary Port-A/Port-B corridor;
- a single simultaneous 32-bit MCU write capture and unqualified AHB
  address/control/burst modes;
- PLL outputs and phase, duty-cycle, feedback, and bypass modes beyond the
  listed frequency pairs;
- physical bond maps and electrically qualified IO for L100, L64, and Q32;
- exact native wire classes, clock skew, IO, hard-block, package, and broad
  PVT timing;
- option-byte programming as a supported deployment path;
- UART bootloader and native USB DFU transports;
- operation with stock OpenOCD builds that lack AGM's `riscv -dap` target
  extension.

The bundled SERV workload qualifies dependent `addi`, `slli`, `xori`, taken
and not-taken branches, `sw`, backward `jal`, and the true-dual-port register
file path. It is not a complete RV32I compliance suite.

See [docs/STATUS.md](docs/STATUS.md) for the exact support matrix and
[docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) for the silicon
qualification boundary.

## Install

Requirements:

- Python 3.8 or newer;
- Yosys, normally from
  [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases);
- a C++ toolchain, CMake, Boost, and Eigen to build the pinned nextpnr
  backend;
- optionally, `riscv64-unknown-elf-gcc` for MCU firmware.

```bash
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
pip install -e .

export AGAMEMNON_OSS=/opt/oss-cad-suite
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
```

On Windows PowerShell, set environment variables with
`$env:NAME = "value"`. A native MinGW nextpnr build can use
`AGAMEMNON_UARCH_NEXTPNR_RUNTIME` to name its own runtime DLL directory.
AGaMEMnon launches Yosys and nextpnr in isolated environments and preflights
the nextpnr loader before routing.

## Build a design

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
```

This writes:

```text
counter.bin       99,944-byte uncompressed SRAM image
counter.bin.comp  compressed flash image
counter_routed.json
```

Use an L48 PCF for package pins:

```bash
agamemnon build examples/designs/comb.v --uarch \
  --pcf examples/constraints/comb_proven_L48.pcf -o comb.bin
```

`AGAMEMNON_DEVICE` defaults to `AGRV2KL48`. Legal package names are
`AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`; physical PCF routing
is supported only for L48.

## Run the hardware examples

- [SERV blinky](examples/serv_blinky/README.md) runs a SERV CPU with a true
  dual-port BRAM register file and drives L48 PIN_25.
- [Serial mux](examples/serial_mux/README.md) receives three simultaneous UART
  streams on L48 PIN_10/11/15 and transmits their round-robin merge on PIN_16.
- [MCU/fabric loopback](examples/loopback/README.md) exercises the MCU GPIO
  bridge through fabric LUTs.

All three use the public synthesis, P&R, and bitgen path. The SERV and serial
mux routes require no qualified checkpoint.

## Program a board

Hardware commands require a CMSIS-DAP probe and an OpenOCD executable with
AGM's `target create riscv -dap` extension:

```bash
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd

agamemnon probe
agamemnon sram firmware.bin --fabric design.bin
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

`sram` is volatile. `flash` erases every touched 4-KiB sector, programs it
through the open controller implementation, reads it back, and compares the
bytes. Back up the complete 256-KiB flash before writing and preserve the
factory decompressor sector when replacing the compressed fabric image.

See [docs/PROGRAMMING.md](docs/PROGRAMMING.md) before a persistent write.

## Command groups

| Command | Purpose |
|---|---|
| `build` | Verilog to routed uncompressed and compressed fabric images |
| `pack` / `unpack` | Routed nextpnr JSON to image, or image to raw configuration |
| `decode` / `encode` | Compressed `.bin` to raw configuration and back |
| `to-agasc` / `from-agasc` | Image to lossless named per-tile text and back |
| `edit-lut` | Change a placed LUT truth table without rerouting |
| `verify` | Simulate a routed netlist and check reachable MCU read values |
| `probe` / `sram` | Identify a board or load a volatile design |
| `backup` / `flash` / `image` | Inspect and update flash regions |

The complete command reference is [docs/USAGE.md](docs/USAGE.md).

## Repository layout

```text
agamemnon/        Python package, synthesis maps, backend source, and chip DB
mcu/              freestanding AG32 MCU headers and linker scripts
examples/         runnable RTL, PCFs, firmware, and bitstream recipes
qualification/    reproducible software and silicon evidence
tests/            unit, integration, packaging, and build regressions
docs/             user, architecture, format, and programming reference
```

Large derived chip-database files use Git LFS and are included in the wheel.
No AGM executable, proprietary routed design, or vendor flash driver is part
of the release flow.

## Documentation

- [Support matrix](docs/STATUS.md)
- [Usage](docs/USAGE.md)
- [Programming](docs/PROGRAMMING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Bitstream format](docs/BITSTREAM_FORMAT.md)
- [Hardware qualification](docs/HARDWARE_VALIDATION.md)
- [Examples](examples/README.md)

## Name

AGaMEMnon. Listen, I had 'AG' to work with, and something about 'MEMory'. I named it before Nolan's Odyssey came out.