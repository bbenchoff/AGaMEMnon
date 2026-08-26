# AGaMEMnon

The [AG32](https://www.agm-micro.com/) is a microcontroller with a small FPGA
bolted to it. It's a real RV32IMAFC core with hard peripherals (UART, SPI, I²C,
CAN, USB, Ethernet MAC, timers, ADC/DAC, GPIO), _plus_ a small programmable
fabric sitting between those peripherals and the pins:
<p align="center">
<table>
<tr>
<th align="left">RISC-V MCU</th>
<th align="left">FPGA fabric</th>
</tr>
<tr valign="top">
<td>
<ul>
<li>RV32IMAFC core, up to 248&nbsp;MHz, hardware FPU</li>
<li>256&nbsp;KB Flash (zero-wait), 128&nbsp;KB SRAM</li>
<li>5&times; UART &middot; 2&times; I²C &middot; SPI</li>
<li>1&times; CAN&nbsp;2.0 &middot; USB&nbsp;FS+OTG &middot; Ethernet MAC</li>
<li>3&times; 12-bit ADC (17&nbsp;ch, 3&nbsp;MSPS) &middot;
2&times; 10-bit DAC</li>
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
<li>architecture advertises up to 128 fabric I/O</li>
</ul>
</td>
</tr>
</table>
</p>

The fabric can be independent logic, a pin-routing layer for hard peripherals,
or a memory-mapped coprocessor beside the MCU. The
[AG32 overview](docs/AG32_OVERVIEW.md) explains the device, naming, clocks,
boot paths, packages, and documentation landscape.

The vendor architecture makes the fabric configurable glue between many hard
peripheral signals and package pads. In principle that permits flexible UART
placement, state machines in signal paths, memory-mapped custom peripherals,
and runtime muxing. Think of the AG32 as something like the Raspberry Pi Pico,
with even better PIOs, or something like the Cypress PSoC, but not limited to
vendor-designed peripherals.

The AG32 has almost no English-language documentation. The 'normal' way to
build a bitstream is a Windows-only Altera Quartus II fork you fetch from a
Baidu Netdisk link (password `12ej`), driving a black-box fabric back-end,
`af.exe`. There is no Linux path and no open format. Fuck you if you want to
use this chip as intended.

*AGaMEMnon* takes Verilog and produces a flashable AG32 fabric bitstream
— synthesis, pack, place, route, bitstream generation, and programming, with no
vendor binary in the path. It's an SDK for the RISC-V half of this chip. This is
an open toolchain for a weird combination RISC-V microcontroller and FPGA.

This is [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has
heard of. Verilog synthesizes, places, routes, and runs on real silicon:
combinational and sequential logic, counters and state machines, clocking
across the array, output to real pins, and the RISC-V core reading and writing
the fabric over its memory bus. There's a writeup of how it works
[here](http://bbenchoff.com/pages/AGaMEMnon.html).

Watch the video demo:

[![AGaMEMnon video demo][video-thumbnail]][video-demo]

[video-thumbnail]: https://img.youtube.com/vi/udDq3NHxerc/maxresdefault.jpg
[video-demo]: https://www.youtube.com/watch?v=udDq3NHxerc

## What This Reverse-Engineering Project _Is_

The purpose of this repo is to build an open-source alternative to the AG32 vendor toolchain. This vendor toolchain is based on Yosys, Quartus, and the `af.exe` application. The vendor toolchain works something like this:

* *Yosys* -- The vendor toolchain ships a modified version of Yosys. This is used to generate the synthesis. With this, Yosys maps Verilog to cells and eventually ALTA primatives. This project RE'd the vendor copy of Yosys to determine the cell/primative library - LUTs/BRAM/carry/IO definitions. The embedded copy of Yosys does not do placement or routing.
* *`af.exe`* -- The fabric back-end. It does the pack, place, route, bitstream generation, and flash-file output. It's a Windows binary, carrying an embedded Tcl interpreter and the architecture database (routing/mux topology, clock/PLL, config-chain bit maps) wrapped in a reversible substitution cipher this project recovered. `af.exe` has no model of which wires actually conduct on silicon and will route an electrically dead edge without hesitation. The bitstream encoding, the routing selectors, and the config-bit maps live here and nowhere else. Recovering `af.exe` is the bulk of this project, involving Ghidra, differential builds against the vendor output, and silicon replication of what _should_ happen.
* *Quartus* -- The vendor toolchain ships with Quartus and `Supra.exe`, tools that handle a migration from Altera MAX II/Cyclone parts over to the AG32 and other AGM FPGAs/CPLDs. Quartus doens't actually do anything relating to packing, placing, or routing. That's all done through `af.exe`.

This project is not really about reverse-engineering an FPGA. This is a project for reverse-engineering the `af.exe` tool that ships with the vendor toolchain, then porting that to nextpnr. `af.exe` is a conduction-blind router, and it has no model of what wires on the silicon actually conduct. The only way to actually figure out how this chip works is through running Verilog through `af.exe`. This was easy, and can be easily solved by having an LLM take a crack at it. The result is a full route routing grid, the map of what the fabric of the chip _should_ look like.

However, `af.exe` is only the ground truth for the encodings. It does not provide any information on conduction, and doesn't know what works on silicon. The actual focus of AGaMEMnon is figuring out what works, and porting that to nextpnr. Most of this repo is figuring that out, and because a bitstream that doesn't map to conduction in the fabric only fails silently, we need rules. This entire project aims to make a silently-wrong bitstream impossible.

You may have noticed that the vendor toolchain, `af.exe` is blind to conduction when creating bitstreams. This implies the vendor toolchain can emit bitstreams that don't do what they're supposed to. Either they fail silently, or they're just _wrong_. This has been witnessed when feeding verilog to `af.exe`. The output of this project will never emit a bitstream that will fail on real silicon.

## Quick start

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python3 -m pip install -e ".[programming]"
agamemnon doctor --no-hardware
```

All required data is stored as ordinary Git objects; Git LFS is not required.
The repository includes a routed counter fixture that can be verified without
a board or FPGA toolchain:

```sh
agamemnon verify tests/fixtures/counter_ahb_routed.json --cycles 8
```

Create the fabric-free starting project:

```sh
agamemnon new hello --board ag32vf303-l48
cd hello
agamemnon build
agamemnon run --transport dap
```

This default needs only a compatible RISC-V GCC and runs from volatile SRAM.
`agamemnon doctor` reports separate inspection, MCU-build, fabric-build, and
hardware-transport capabilities.

Two larger templates are exact replays, not generic promises:

- `--template mcu-fpga` replays the reviewed L48 public32 AHB map: ID32
  `0x4147414d` at +0, scratch16 at +4, counter3 at +8, and W1C1 at +c.
- `--template serv-blinky` replays one retained L48 SERV route. Fresh arbitrary
  SERV placement, a fresh full parity claim, and wider direct-D placement are
  outside this profile.

The current checkout intentionally has a review gate on the public32
composition. If the composer reports `candidate hash does not match reviewed
artifact`, stop and review the semantic drift; do not repin the hash to make the
test green. See [Landing a chip-database change](docs/LANDING_A_CHIPDB_CHANGE.md).

## Hardware safety

SWD/DAP is the beginner-safe transport: it works on a stock board and supports
volatile MCU/fabric loads. The USB CDC uploader is convenient only after its
loader is installed. The Pico-driven UART0 mask-ROM path is the
flash-independent recovery route. Read [Programming](docs/PROGRAMMING.md) before
any persistent write and compare the setup with
[Known-good hardware](docs/KNOWN_GOOD_HARDWARE.md).

## Documentation

| Read | For |
|---|---|
| [Status](docs/STATUS.md) | authoritative support, exclusions, open defects, and current test state |
| [Vendor parity](docs/VENDOR_PARITY.md) | the 105-design campaign and its evidence limits |
| [Installation](docs/INSTALLATION.md) | host tools, bundles, and drivers |
| [Usage](docs/USAGE.md) | command reference and strict-build behavior |
| [Projects](docs/PROJECTS.md) | manifests and exact replay templates |
| [Programming](docs/PROGRAMMING.md) | DAP, USB, UART, and persistent-write safety |
| [Examples](examples/README.md) | runnable RTL and firmware with per-example scope |
| [MCU SDK](sdk/README.md) | open HAL coverage and qualification tiers |
| [MCU HAL reference](docs/HAL_MCU_REFERENCE.md) | MCU registers, drivers, and provenance |
| [FPGA HAL reference](docs/HAL_FPGA_REFERENCE.md) | fabric resources and configuration fields |
| [Architecture](docs/ARCHITECTURE.md) | synthesis, routing, bitgen, and verification layers |
| [Routing admission](docs/ROUTING_ADMISSION.md) | selector policy and what admission does not prove |
| [MCU/fabric boundary](docs/MCU_AHB_REGISTER_BANK.md) | exact AHB compositions and remaining gaps |
| [Hardware validation](docs/HARDWARE_VALIDATION.md) | board-observed evidence, including negative results |
| [Roadmap](ROADMAP.md) | prioritized correctness, breadth, and release work |
| [Notices](NOTICE.md) | licensing and recovered-data provenance |

The detailed [documentation index](docs/AG32_OVERVIEW.md#documentation-map)
links the remaining bitstream, clock, pin-routing, peripheral, qualification,
and research records.

## Contributing and support

New hardware evidence is especially valuable. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or qualification
records. Use [SUPPORT.md](SUPPORT.md) for unexpected behavior and
[SECURITY.md](SECURITY.md) for security reports. User-visible changes are in
[CHANGELOG.md](CHANGELOG.md).

## The name

AGaMEMnon: “AG” plus something about memory. It was named before Nolan's
*Odyssey* came out.
