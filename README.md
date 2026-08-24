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

All required data is stored as normal Git objects; Git LFS is not required.

Try it without a board or FPGA toolchain — the repository contains a routed
counter fixture:

```sh
agamemnon verify tests/fixtures/counter_ahb_routed.json --cycles 8
```

Then create and run a first project:

```sh
agamemnon new hello --board ag32vf303-l48    # default template: fabric-free MCU blink
cd hello
agamemnon build                              # MCU-only -> needs just RISC-V GCC
agamemnon run --transport dap                # run on a connected board (volatile SRAM)
```

To exercise the MCU/fabric boundary, use `--template mcu-fpga`. It strictly
replays one immutable, hash-bound L48 route: the default public32 map returns
canonical ID32 `0x4147414d` at offset 0 and zero-extended writable scratch16
at +4, with counter3 at +8 and W1C1 status at +c. The firmware reads and
writes those registers. This exact profile is silicon-qualified; it does not
promote the generic decoded-only `AGAMEMNON_MCU_ENTRY` route option. See
[the register-bank boundary](docs/MCU_AHB_REGISTER_BANK.md).

For the CPU-scale example, `--template serv-blinky` strictly replays the
retained public L48 SERV route and builds its volatile-SRAM loader. The exact
profile is supported; fresh arbitrary SERV/direct-D placement remains
fail-closed. See [the SERV example](examples/serv_blinky/README.md).

Setup comes in tiers, and `agamemnon doctor` reports which one you are at:
Python 3.8+ alone covers inspection, conversion, and offline verification;
the bundled `riscv-none-elf-gcc` (or compatible `riscv64-unknown-elf-gcc`)
adds MCU firmware builds; Yosys and the AGRV2K
nextpnr backend add fabric builds; a CMSIS-DAP probe plus AGaMEMnon's
qualified OpenOCD (`agamemnon install-openocd`) adds programming. See
[Installation](docs/INSTALLATION.md).

## Hardware

The beginner-safe transport is SWD/DAP: it works on an untouched stock board
and can recover one. The USB CDC uploader becomes the convenient application
transport after its loader is installed, and the Pico-driven UART0 mask ROM is
the flash-independent recovery path. Read [Programming](docs/PROGRAMMING.md)
before any persistent write, and compare your board against
[known-good hardware](docs/KNOWN_GOOD_HARDWARE.md) first.

## Documentation

| Read | For |
|---|---|
| [AG32 overview](docs/AG32_OVERVIEW.md) | the device, naming, clocks, boot paths, and vendor sources |
| [Support matrix](docs/STATUS.md) | exactly what is supported and silicon-qualified |
| [Installation](docs/INSTALLATION.md) | toolchains and drivers on Windows, Linux, and macOS |
| [Usage](docs/USAGE.md) | the complete command reference |
| [Projects](docs/PROJECTS.md) | manifests, templates, and the project model |
| [Programming](docs/PROGRAMMING.md) | SWD/DAP, USB CDC, and UART transports and safety flow |
| [Examples](examples/README.md) | runnable RTL, firmware, PCFs, and bitstream recipes |
| [MCU SDK](sdk/README.md) | the open HAL and its qualification state |
| [**MCU HAL reference**](docs/HAL_MCU_REFERENCE.md) | **every MCU-half subsystem: register maps, bitfields, the HAL header that covers it, and each claim's provenance tier** |
| [**FPGA HAL reference**](docs/HAL_FPGA_REFERENCE.md) | **every fabric-half resource: tiles, slices, carry, BRAM, PLL/clocks, IO ring, the config-surface planes, and the bitstream layout** |
| [MCU clocks](docs/MCU_CLOCKS.md) | core versus fabric clocks, transition rules, and current limits |
| [MCU pin routing](docs/MCU_PIN_ROUTING.md) | alternate-function semantics and silicon-backed route policy |
| [Architecture](docs/ARCHITECTURE.md) | the recovered fabric, router, and bitstream internals |
| [Routing admission](docs/ROUTING_ADMISSION.md) | the three-tier default routing model, the confidence manifest, and `--release-strict` |
| [Bitstream format](docs/BITSTREAM_FORMAT.md) | compressed/raw containers, CRC, physical features, and selector policy |
| [MCU External AHB](docs/MCU_AHB_REGISTER_BANK.md) | the qualified constant endpoint and remaining sequential register-bank boundary |
| [Vendor parity](docs/VENDOR_PARITY.md) | the demonstrated, bounded vendor-parity profile and what it does and does not cover |
| [MCU/fabric roadmap](docs/MCU_FABRIC_ROADMAP.md) | unfinished AHB, interrupt, DMA, GPIO, and hard-block work |
| [Hardware qualification](docs/HARDWARE_VALIDATION.md) | the silicon evidence boundary |
| [Claim policy ledger](docs/CLAIM_POLICY_LEDGER.md) | per-feature maturity and evidence tier under the D0 policy, for bitstream-engine features only (generated; not a peripheral or HAL ledger) |
| [Research knowledge profile](docs/ENGINE_CONFIGURATION.md#research-unsafe-recovered-knowledge-profile) | opt-in vendor-derived/conflicted/predicted data and provenance rules |
| [S2 release audit](docs/RELEASE_S2_AUDIT.md) | cold-build, wheel, and example evidence plus the remaining release blockers |
| [Engine refactor](docs/ENGINE_REFACTOR.md) | the executed feature-module engine design and its byte-identity migration record |
| [Qualification reports](docs/QUALIFICATION_REPORT.md) | read-only, reviewable support-evidence intake |
| [Roadmap](ROADMAP.md) | known limitations and prioritized work |
| [Notices](NOTICE.md) | provenance and the licensing boundary |

## Contributing and support

New hardware evidence is especially valuable. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or qualification
records, use [SUPPORT.md](SUPPORT.md) when something does not behave as
documented, and report security problems according to
[SECURITY.md](SECURITY.md). User-visible changes are recorded in
[CHANGELOG.md](CHANGELOG.md). Participation is governed by the
[code of conduct](CODE_OF_CONDUCT.md).

## The Name

AGaMEMnon. I had 'AG' to work with, and something about 'MEMory'. I named 
it before Nolan's *Odyssey* came out. I am also mentally preparing for
[Marc Andreessen quoting Aeschylus when Trump finally dies](https://x.com/pmarca/status/1865145956230140134).
