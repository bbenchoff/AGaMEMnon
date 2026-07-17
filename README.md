# AGaMEMnon

The [AG32](https://www.agm-micro.com/) is not quite a microcontroller and not quite a normal FPGA. It's a real RV32IMAFC core with hard peripherals (UART, SPI, I²C, CAN, USB, Ethernet MAC, timers, ADC/DAC, GPIO), _plus_ a small programmable fabric sitting between those peripherals and the pins:
<p align="center">
<table>
<tr>
<th align="left">RISC-V MCU</th>
<th align="left">FPGA fabric</th>
</tr>
<tr valign="top">
<td>
<ul>
<li>RV32IMAFC core @ 248&nbsp;MHz, hardware FPU</li>
<li>256&nbsp;KB Flash (zero-wait), 128&nbsp;KB SRAM</li>
<li>5&times; UART &middot; 2&times; I²C &middot; SPI</li>
<li>1&times; CAN&nbsp;2.0 &middot; USB&nbsp;FS+OTG &middot; Ethernet MAC</li>
<li>3&times; 12-bit ADC (17&nbsp;ch, 3&nbsp;MSPS) &middot; 2&times; 10-bit DAC</li>
<li>2&times; comparator &middot; RTC &middot; watchdog</li>
<li>basic + advanced timers</li>
</ul>
</td>
<td>
<ul>
<li>2112 LUT4s</li>
<li>2112 flip-flops</li>
<li>4 block RAMs</li>
<li>1 PLL</li>
<li>5 global clocks</li>
<li>up to 128 I/O</li>
</ul>
</td>
</tr>
</table>
</p>

The fabric is configurable glue that attaches almost any pin to any peripheral. Route a UART to almost any pin, drop a state machine into a signal path, add a small custom peripheral next to the CPU, mux at runtime, and have it all configure from SPI flash at boot. That makes the AG32 good for flexible pin assignment, protocol glue, deterministic IO, and small custom hardware without a separate FPGA. It's a bit like a Cypress PSoC, except the programmable part is an actual FPGA bolted to a RISC-V core.

The AG32 has almost no English-language documentation. The sanctioned way to build a bitstream is a Windows-only Altera Quartus II fork you fetch from a Baidu Netdisk link (password `12ej`), driving a black-box fabric back-end, `af.exe`. There is no Linux path and no open format. Fuck you if you want to use this chip as intended.

*Project AGaMEMnon* takes Verilog and produces a flashable AG32 fabric bitstream — synthesis, pack, place, route, bitstream generation, and programming, with no vendor binary in the path:

```text
Verilog  →  yosys           open synthesis (RTL → AGRV2K LUT4/FF cells)
         →  nextpnr         open pack / place / route (the recovered AGRV2K device + our `agrv2k` uarch)
         →  agamemnon pack  open bitstream generation (routed design → logic.bin)
         →  agamemnon flash open programming (logic.bin → chip over SWD, CMSIS-DAP)
```

It's [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has heard of. Verilog synthesizes, places, routes, and runs on real silicon: combinational and sequential logic, counters and state machines, clocking across the array, output to real pins, and the RISC-V core reading and writing the fabric over its memory bus. There's a writeup of how it works [here](http://bbenchoff.com/pages/AGaMEMnon.html).



## Supported feature set

Nearly all of the features of the AG32 vendor FPGA toolchain is supported:

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
| Programming | SWD probe and SRAM loading; verified flash writes over SWD; Pico-controlled UART0 ROM backup/program/reset path (target wiring qualification pending); silicon-qualified L48 flash-resident USB CDC uploader |

There are a few places where this support fails:

- carry spill outside the qualified 33-site corridor, multiple long carry chains, branched carry, and malformed chains;
- general BRAM placement across every tile, width, initialization layout, write/collision mode, and arbitrary Port-A/Port-B corridor;
- a single simultaneous 32-bit MCU write capture and unqualified AHB address/control/burst modes;
- PLL outputs and phase, duty-cycle, feedback, and bypass modes beyond the listed frequency pairs;
- physical bond maps and electrically qualified IO for L100, L64, and Q32;
- exact native wire classes, clock skew, IO, hard-block, package, and broad PVT timing;
- option-byte programming as a supported deployment path;
- native USB ROM/DFU transport, target-side silicon qualification of the new Pico UART bootloader transport, and using the flash-resident USB CDC uploader as recovery when main flash is corrupt;
- operation with stock OpenOCD builds that lack AGM's `riscv -dap` target extension.

See [docs/STATUS.md](docs/STATUS.md) for the exact support matrix and [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) for the silicon qualification boundary.

## Quickstart

Setup comes in three tiers — you only need as much as your goal. `agamemnon doctor` reports which tier you are at.

| Goal | What you need |
|---|---|
| Inspect/convert bitstreams, scaffold a project, run offline verify/sim | Python 3.8+ only |
| Build fabric from Verilog | + Yosys and the AGRV2K nextpnr |
| Program a board | + an AG32 board, a CMSIS-DAP probe, and a compatible OpenOCD |

The version-pinned SDK bundle carries Yosys, the AGRV2K nextpnr, RISC-V GCC, and an AGM-capable OpenOCD, so on Linux/Windows one install covers all three tiers.

### Linux (x86-64)

```sh
sh tools/install.sh 0.1.0                    # download + SHA-256-verify the bundle
cd ~/.agamemnon/sdk-0.1.0/agamemnon-sdk-linux-x64
. ./activate.sh                              # sets AGAMEMNON_OSS/NEXTPNR/OPENOCD
python3 -m pip install packages/agamemnon_ag32-0.1.0-py3-none-any.whl
agamemnon doctor
```

### Windows (PowerShell)

```powershell
./tools/install.ps1 -Version 0.1.0
cd "$HOME/.agamemnon/sdk-0.1.0/agamemnon-sdk-windows-x64"
./activate.ps1
python -m pip install packages/agamemnon_ag32-0.1.0-py3-none-any.whl
agamemnon doctor
```

### macOS (and any from-source setup)

There is no prebuilt macOS bundle yet, so install the package and bring your own tools:

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python3 -m pip install -e ".[programming]"

# Tier 2 (fabric builds):
#   Yosys   -> OSS CAD Suite ships macOS/arm64 builds; export AGAMEMNON_OSS=/path
#   nextpnr -> build the agrv2k backend from source (see Install, below)
# Tier 3 (hardware): a compatible OpenOCD must be built locally
#   (AGM ships the riscv -dap target prebuilt for Windows only -- see Known limitations)

agamemnon doctor
```

### First project (any OS, once installed)

```sh
agamemnon new hello --board ag32vf303-l48    # default template: fabric-free MCU blink
cd hello
agamemnon build                              # MCU-only -> needs just RISC-V GCC
agamemnon run --transport dap                # run on a connected board (volatile SRAM)
```

The default template needs no FPGA toolchain. For the MCU↔FPGA bridge demo use `--template mcu-fpga` (that one runs Yosys and nextpnr).

No board yet? These work with Python alone, on every OS:

```sh
agamemnon decode fabric.bin -o raw.img               # inspect a bitstream
agamemnon to-agasc fabric.bin -o fabric.agasc        # lossless named text you can edit
agamemnon verify design_routed.json --cycles 64      # offline sim of a routed design
```

Environment variables set by `activate.*` (or by hand for a source setup) are listed in [docs/USAGE.md](docs/USAGE.md); the full install reference is [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Install

For normal SDK use, download the version-matched Windows or Linux bundle from the GitHub release, activate it, install its wheel, and diagnose the complete host/board path:

```text
agamemnon --version
agamemnon doctor
```

See [the installation guide](docs/INSTALLATION.md). The manual build below is for toolchain development.

Requirements:

- Python 3.8 or newer;
- Yosys, normally from [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases);
- a C++ toolchain, CMake, Boost, and Eigen to build the pinned nextpnr backend;
- optionally, `riscv64-unknown-elf-gcc` for MCU firmware.

```bash
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
pip install -e .

export AGAMEMNON_OSS=/opt/oss-cad-suite
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
```

On Windows PowerShell, set environment variables with `$env:NAME = "value"`. A native MinGW nextpnr build can use `AGAMEMNON_UARCH_NEXTPNR_RUNTIME` to name its own runtime DLL directory. AGaMEMnon launches Yosys and nextpnr in isolated environments and preflights the nextpnr loader before routing.

## Start a project

```text
agamemnon new hello --board ag32vf303-l48 --template mcu-fpga
cd hello
agamemnon doctor
agamemnon build
agamemnon run --transport dap
```

The manifest records multiple Verilog and MCU sources, the top module, linker, board/package, PCF, clocks, outputs, and flash layout. See [PROJECTS.md](docs/PROJECTS.md). One-off single-file builds remain available.

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

`AGAMEMNON_DEVICE` defaults to `AGRV2KL48`. Legal package names are `AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`; physical PCF routing is supported only for L48.

## Run the hardware examples

- [RISC-V MCU firmware](examples/riscv_mcu/README.md) includes a volatile SRAM signature, persistent reset counter, and LED blink images for native flash boot or USB upload/`GO`.
- [SERV blinky](examples/serv_blinky/README.md) runs a SERV CPU with a true dual-port BRAM register file and drives L48 PIN_25.
- [Serial mux](examples/serial_mux/README.md) receives three simultaneous UART streams on L48 PIN_10/11/15 and transmits their round-robin merge on PIN_16.
- [MCU/fabric loopback](examples/loopback/README.md) exercises the MCU GPIO bridge through fabric LUTs.

The fabric-oriented examples use the public synthesis, P&R, and bitgen path. The MCU-only example does not require an RTL build. The SERV and serial-mux routes require no qualified checkpoint.

## Program a board

Choose a transport deliberately:

| Transport | Untouched stock board | Recovery capable | Hardware modification |
|---|---|---|---|
| SWD/DAP | Yes, with compatible OpenOCD | Yes | No |
| USB CDC uploader | No; install the loader once | No; loader lives in main flash | No |
| UART mask ROM/Pico | ROM supports it | Yes | **Yes on the current L48 board/harness** |

The beginner-safe path is DAP/SWD. USB becomes the convenient application transport after its loader has been installed. UART is not a plug-in stock board alternative: read [the required hardware change](docs/UART_BOOTLOADER.md) first.

Hardware commands require a CMSIS-DAP probe and an OpenOCD executable with AGM's `target create riscv -dap` extension:

```bash
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd

agamemnon probe
agamemnon sram firmware.bin --fabric design.bin
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin

# After making the documented L48 harness change, use Pico/UART recovery:
agamemnon uart-probe --port COM6
agamemnon uart-flash firmware.bin --addr 0x80000000 \
  --backup pre-write.bin --port COM6
```

`sram` is volatile. `flash` erases every touched 4-KiB sector, programs it through the open controller implementation, reads it back, and compares the bytes. Back up the complete 256-KiB flash before writing and preserve the factory decompressor sector when replacing the compressed fabric image.

See [docs/PROGRAMMING.md](docs/PROGRAMMING.md) before a persistent write. The stock board has USB-capable hardware but does not ship with the qualified CDC uploader in flash. Install it once over SWD or UART0 ROM before expecting the right-hand target USB-C connector to accept programming commands.

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
| `uart-probe` / `uart-backup` / `uart-flash` / `uart-reset` | Recover and program through the Pico-controlled UART0 ROM |
| `new` / project `build` / `run` / `monitor` | Create and use manifest-backed MCU/fabric projects |
| `doctor` | Diagnose tools, runtime libraries, serial devices, probes, and connected AG32 targets |

The complete command reference is [docs/USAGE.md](docs/USAGE.md).

## Repository layout

```text
agamemnon/        Python package, synthesis maps, backend source, and chip DB
mcu/              freestanding AG32 MCU headers and linker scripts
sdk/              MCU SDK strategy and optional CMake integration
examples/         runnable RTL, PCFs, firmware, and bitstream recipes
qualification/    reproducible software and silicon evidence
tests/            unit, integration, packaging, and build regressions
docs/             user, architecture, format, and programming reference
```

Large derived chip-database files use Git LFS and are included in the wheel. No AGM executable, proprietary routed design, or vendor flash driver is part of the release flow.

## Documentation

- [Support matrix](docs/STATUS.md)
- [Usage](docs/USAGE.md)
- [Installation and pinned bundles](docs/INSTALLATION.md)
- [Projects and templates](docs/PROJECTS.md)
- [MCU SDK strategy](sdk/README.md)
- [Programming](docs/PROGRAMMING.md)
- [RISC-V MCU programming](docs/RISCV_MCU_PROGRAMMING.md)
- [MCU and FPGA peripheral examples](docs/PERIPHERAL_EXAMPLES.md)
- [Pico UART bootloader findings and hardware](docs/UART_BOOTLOADER.md)
- [Flash-resident USB CDC uploader](docs/USB_CDC_UPLOADER.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Engine configuration and evidence registry](docs/ENGINE_CONFIGURATION.md)
- [Bitstream format](docs/BITSTREAM_FORMAT.md)
- [Hardware qualification](docs/HARDWARE_VALIDATION.md)
- [Examples](examples/README.md)

## Known limitations and roadmap

These are known gaps a newcomer will hit. They are tracked, not hidden.

- **A redistributable compatible OpenOCD is still blocked on corresponding source.** Every SWD/DAP hardware command needs AGM's `riscv -dap` target extension; stock upstream and OSS CAD Suite builds do not provide it. The pinned os-q Windows package works, but its repository contains GPLv2 binaries without the corresponding patched source. The bundle builder now parser-probes `-dap` and refuses to publish OpenOCD without an unpacked GPL source tree. Until that source is recovered or the extension is reimplemented upstream, obtain the compatible binary separately. The Pico mask-ROM UART path needs no OpenOCD.

- **The open HAL is useful but not complete or broadly silicon-qualified.** In addition to GPIO4, CLINT, a basic timer, and FCB, it now has published-register polling APIs for UART, the eight-phase SPI master, I2C master, System Control, and memory-to-memory DMA (see [sdk/README.md](sdk/README.md)). Their layouts and firmware compile in CI; UART/DMA have a safe internal-loopback qualification candidate. CAN, USB, RTC, watchdog, ADC/DAC/comparator, flash, CRC, Ethernet, interrupts, alternate-function policy, and DMA peripheral request helpers still need open drivers and board-level qualification.

- **Scope is deliberately narrow and L48-bound.** Physical `PIN_n` routing exists only for AGRV2KL48; one BRAM Port-A/Port-B path is qualified; dedicated carry is limited to same-tile chains and one 33-site corridor; the SERV workload proves seven instruction forms, not RV32I compliance; the timing report is a conservative estimate, not a silicon Fmax model. See [docs/STATUS.md](docs/STATUS.md) for the exact boundary.

- **Engine-core size remains technical debt, but configuration is no longer implicit.** All 55 engine switches now have typed defaults, scope, maturity, and in-repository evidence in [the engine registry](docs/ENGINE_CONFIGURATION.md); high-impact fitted constants are shared by architecture generation and bitgen. `arch.py` and `bitgen_seq.py` are import-safe callable entry points. They remain large and should be decomposed by subsystem, with byte-exact pack tests and generated-device graph tests guarding each extraction.

## Name

AGaMEMnon. Listen, I had 'AG' to work with, and something about 'MEMory'. I named it before Nolan's Odyssey came out.
