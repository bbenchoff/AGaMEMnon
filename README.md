# Project AGaMEMnon

AGaMEMnon is an open synthesis, place-and-route, bitstream, and programming
toolchain for the AGM AG32 / AGRV2K embedded FPGA fabric. The chip combines an
RV32IMAFC microcontroller with 2,112 LUT4s, 2,112 flip-flops, four 9-Kbit block
RAMs, a PLL, global clocks, and a programmable IO ring.

The release fabric path contains no vendor executable:

```text
Verilog -> Yosys -> nextpnr `agrv2k` uarch -> AGaMEMnon bitgen -> AG32
```

AGaMEMnon also decodes, edits, and re-encodes fabric images; provides a
lossless named `.agasc` representation; verifies routed sequential designs;
and drives the chip's flash controller without the vendor OpenOCD flash
driver.

## Current capability

| Area | Current support |
|---|---|
| RTL | Combinational and sequential Verilog, LUT4/FF packing, clocks, counters, state machines, and large designs through the `agrv2k` backend |
| Routing | Release graph uses exact conflict-free physical selectors and unanimous tile-relative selectors; bitgen rejects unresolved or predicted release selectors |
| Scale | 72/72 randomized 16/32/64-bit builds pass; the current true-dual-port SERV example routes through the public flow and runs on silicon |
| Carry | Opt-in dedicated Cin/Cout lowering; single 4- and 8-stage chains and two simultaneous 3-stage chains are silicon-qualified in one tile |
| BRAM | Port A is silicon-qualified in one characterized x18 path; one exact x2 Port-B read/control corridor is also silicon-qualified; other widths, tiles, collision modes, and arbitrary fresh corridors remain open |
| PLL | Byte-exact `(SYSCLK,HSE)` pairs: `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz; the SRAM stub restores the selected PLL after configuration |
| MCU bridge | GPIO loopback and narrow External-AHB write are silicon-qualified; ten read lanes are exposed and nine were observed simultaneously |
| Physical IO | L48 bond map and characterized top-row paths; qualified PIN10, PIN11, PIN15, and PIN19 input paths plus selected header/LED-pad outputs |
| Timing | Fail-closed frequency target with conservative cell arcs and worst-case mux-family wire delays |
| Bitstreams | LZW `.bin`, raw image, CRC-32/BZIP2, LUT editing, and lossless `.agasc` round trips |
| Programming | SRAM injection, flash backup, erase/program/verify, and boot from the factory compressed-config location |

The current limits are explicit:

- Dedicated carry does not spill between tiles.
- Fresh BRAM routes still need pin-specific conducting corridors. One x2
  Port-B path is qualified, but arbitrary Port-B placement, other widths and
  tiles, narrow-mode initialization, and collision semantics are not.
- SERV's shipped aliased `addi`/`sw` workload runs; broader multi-instruction
  signature programs and SERV-density routing to onboard LED PIN_25 remain
  unqualified.
- The MCU bridge is not a full 32-bit transfer in either direction.
- PLL output/phase/duty/bypass coverage is limited to the listed ratios and
  mode.
- L100, L64, and Q32 have package-pin legality data but no physical bond maps.
- Timing does not yet model exact native wire classes, clock skew, IO,
  hard-block, or package delays.
- UART bootloader and native USB DFU programming are not implemented.
- SWD programming needs an OpenOCD executable containing AGM's unpublished
  `target create riscv -dap` extension. The flash-controller implementation
  and OpenOCD configuration in this repository are open.

See [docs/STATUS.md](docs/STATUS.md) for the evidence-backed support boundary.

## Install and build

Requirements:

- Python 3.8 or newer
- Yosys and nextpnr, normally from
  [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build/releases)
- a C++ build environment for the pinned nextpnr overlay
- optionally, `riscv64-unknown-elf-gcc` for MCU firmware

```bash
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
pip install -e .

export AGAMEMNON_OSS=/opt/oss-cad-suite
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"

agamemnon build examples/designs/counter_ahb.v --uarch --verify -o counter.bin
```

On Windows PowerShell, set the same variables with `$env:NAME = "value"`. If
the native nextpnr build depends on MSYS2/MinGW DLLs, also point
`AGAMEMNON_UARCH_NEXTPNR_RUNTIME` at that build's `mingw64\bin` directory.
AGaMEMnon keeps the Yosys and nextpnr DLL environments separate and preflights
nextpnr before routing.
The build writes a 99,944-byte uncompressed SRAM image and a compressed
`<output>.comp` flash image.

Use a PCF for package pins:

```bash
agamemnon build examples/designs/comb.v --uarch \
  --pcf examples/constraints/comb_proven_L48.pcf -o comb.bin
```

`AGAMEMNON_DEVICE` defaults to `AGRV2KL48`; accepted values are
`AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`. Physical PCF builds
currently require the L48 bond map.

## Programming

Hardware commands require a CMSIS-DAP probe and a compatible OpenOCD binary:

```bash
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd

agamemnon probe
agamemnon sram firmware.bin --fabric design.bin
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

`sram` is volatile. `flash` erases every 4-KiB sector touched by the input,
programs it through the controller at `0x40001000`, reads it back, and compares
the bytes. Back up the full 256-KiB flash before writing.

The factory compressed layout includes a decompressor blob before the config.
Do not erase only part of a shared decompressor/config sector. Writing a
compressed image at the existing factory config address (`0x80008100` on the
qualified board) preserves the already-programmed option pointers. Programming
new option-byte pointers is exposed only through the explicitly unverified
`image --write-options` path.

Full programming details are in
[docs/PROGRAMMING.md](docs/PROGRAMMING.md).

## Commands

| Command | Purpose |
|---|---|
| `build` | Verilog -> Yosys -> nextpnr -> uncompressed and compressed fabric images |
| `pack` / `unpack` | Routed nextpnr JSON <-> fabric image |
| `decode` / `encode` | Compressed `.bin` <-> 99,936-byte raw configuration |
| `to-agasc` / `from-agasc` | Fabric image <-> lossless named per-tile ASCII |
| `edit-lut` | Change one placed LUT truth table without rerouting |
| `verify` | Cycle-simulate a routed netlist and report reachable MCU read values |
| `probe` | Read `DEVICE_ID` over SWD |
| `sram` | Load fabric plus MCU firmware into SRAM and run it |
| `backup` | Read the complete 256-KiB flash |
| `flash` | Erase, program, and verify a flash region |
| `image` | Plan or write MCU/fabric regions; option-pointer writes remain opt-in and unverified |

Run `agamemnon <command> --help` for exact arguments. The supported build
controls include `--uarch`, `--pcf`, `--mcu`, `--hard-carry`, `--cap`,
`--maxfo`, `--freq`, `--verify`, `--write-routed`, and
`--qualified-checkpoint`.

## Repository layout

```text
agamemnon/        Python package, CLI, synthesis files, uarch source, chip DB
mcu/              freestanding AG32 MCU header and linker scripts
examples/         RTL, PCFs, firmware, and runnable codec/programming recipes
qualification/    reproducible qualification tools and append-only evidence
tests/            software and build regressions
docs/             architecture, format, usage, programming, and status
```

The large derived chip-database artifacts are tracked with Git LFS and are
included in built wheels. The wheel contains the chip database, synthesis
maps, OpenOCD configuration, and `agrv2k` backend source needed at runtime or
to build the pinned nextpnr overlay.

## Validation

The checked-in software suite covers the codecs, bitstream mapping, selector
recovery, fail-closed routing/bitgen behavior, `.agasc`, timing data, carry,
BRAM Port B representation, routed-netlist verification, and end-to-end build
helpers. Hardware evidence is retained under `qualification/`; routing is
promoted only from isolated path evidence, and negative isolated evidence
overrides corpus correlation.

Current silicon results include combinational and registered IO, physical pin
input/output, MCU GPIO loopback, External-AHB read/write subsets, 4/8-stage and
dual carry chains, a selected x2 Port-B path, verified 10/25/50/100-MHz PLL
restoration after SRAM configuration, randomized 16/32/64-bit RTL, the
collision-free three-input serial merger, and the current true-dual-port SERV
CPU progress demo. See
[docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) for the exact scope.

## License and name

The project is named AGaMEMnon: AG32 plus memory, with the capitalization kept
for the pun.
