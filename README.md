# Project AGaMEMnon

**An open bitstream and place-and-route toolchain for the AGM AG32 / AGRV2K embedded FPGA fabric.**

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
Verilog  →  yosys            open synthesis (RTL → AGRV2K LUT4/FF cells)
         →  nextpnr-generic  open pack / place / route (stock nextpnr + the shipped AGRV2K arch)
         →  agamemnon pack   open bitstream generation (routed design → logic.bin)
         →  agamemnon flash  open programming (logic.bin → chip over SWD, CMSIS-DAP)
```

It's [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has heard of. Verilog synthesizes, places, routes, and runs on real silicon: combinational and sequential logic, counters and state machines, clocking across the array, output to real pins, and the RISC-V core reading and writing the fabric over its memory bus. There's a writeup of how it works [here](http://bbenchoff.com/pages/AGaMEMnon.html).

---

## Using it

One `agamemnon` command drives both halves of the chip — the FPGA fabric and the flash/RISC-V side. No `af.exe`, no Quartus, no Windows, no Baidu, no vendor OpenOCD driver. The FPGA flow maps onto IceStorm one-for-one, so if you know that flow you know this one.

```bash
pip install -e .                                             # the chip database ships with the repo
agamemnon build design.v -o design.bin                       # yosys → nextpnr-generic → bitgen
agamemnon flash design.bin --addr 0x80008100 --backup f.bin  # erase → program → verify
```

| `agamemnon …` | what it does |
|---|---|
| `build design.v` | Verilog → yosys → nextpnr-generic (with the shipped AGRV2K arch) → bitstream `.bin` |
| `pack` / `unpack` | routed nextpnr JSON ↔ flashable `.bin` (icepack / iceunpack) |
| `decode` / `encode` / `edit-lut` | `.bin` ↔ 99,936-byte raw config image; open LUT editor |
| `probe` | read DEVICE_ID over SWD (expect `0x40200001`) |
| `sram fw -b fabric` | SRAM-inject a bitstream + firmware and run it (volatile, no flash write) |
| `flash bin --addr` | erase → program → verify; drives the flash controller directly, no vendor `agrv` driver |
| `image -b fabric -m fw` | assemble a combined boot image (fabric + MCU + config pointer) |
| `backup` | dump the whole 256 KB flash |

The RISC-V side (`mcu/ag32.h` + a linker script) builds with any `riscv64-unknown-elf-gcc`, and `agamemnon image` combines an MCU binary with a fabric bitstream into one flash image that self-boots.

## What runs on silicon

Format claims are checked byte-for-byte against `af.exe`. Hardware claims are checked on a real AG32 (`DEVICE_ID 0x40200001`, RISC-V `misa 0x40801125`).

| Layer | Evidence |
|---|---|
| yosys synthesis (RTL → AGRV2K LUT4/FF) | builds |
| `.bin` LZW codec, both directions | byte-exact vs `af.exe` |
| Fabric-config CRC-32/BZIP2 | accepted by the chip's config engine |
| Physical map — 554,800 bits / 213 tiles, logic and routing | byte-exact |
| Open bitgen (routed design → `.bin`) | silicon; FCB accepts + activates (`STAT=0x000f0002`) |
| nextpnr-generic pack / place / route on the shipped chip database | silicon |
| Combinational logic | silicon; the inverter inverts |
| Flip-flops | silicon; the FF toggles |
| Counters, shift registers, small FSMs, ripple adder | silicon; auto-placed, read back over AHB; dense counters to 16 bits |
| Clock distribution across the array | silicon; FFs clock at near and far tiles |
| Ring-pad output — fabric drives a real header pin | silicon; the pin toggles |
| MCU ↔ fabric GPIO — 4-bit loopback, auto-placed | silicon; 16/16 combinations |
| MCU AHB — CPU writes a fabric register | silicon; `*0x60000000 = v` is captured |
| MCU AHB — CPU reads fabric registers (`hrdata`) | silicon; multi-lane readback, 9 of 10 lanes simultaneously |
| Conduction + clock characterization | silicon-swept across the array |
| Flash-boot — our bitstream self-boots from flash, no debugger | silicon |
| Device / package awareness (L100 / L64 / L48 / Q32) | pin-legality gate; default AGRV2KL48, `AGAMEMNON_DEVICE` |

### The device model is measured, not guessed

nextpnr places and routes correctly against whatever arch you hand it, so the whole problem is handing it an arch that matches the silicon. The config *format* is byte-exact RE and was the easy part. The hard part: which fabric edges actually conduct, and which tiles the clock actually reaches, isn't written down anywhere. The vendor tool computes it per-design inside its router, and you can't extract it at rest.

So AGaMEMnon measures it. An automated silicon sweep forces a signal through every tile and path and records what conducts and what clocks, building a silicon-verified conduction map. The arch is gated on that map, so nextpnr can't pick an edge that doesn't work: dead intra-tile carries are excluded (counters spread onto routes that conduct), non-clocking placements aren't offered, and long routes use only paths proven on silicon. Arbitrary RTL routes and runs because the model matches the part.

## Where it stops

RE of the fabric configuration and the toolchain is done: Verilog goes to running silicon, both halves, no vendor binary. Two things are out of scope by nature:

- **Function, not Fmax.** This isn't [icetime](https://github.com/YosysHQ/icestorm/tree/main/icetime). It ships the vendor delay tables and optimizes for correct, not fast; designs run at a conservative clock. A timing-driven flow with real Fmax closure would be a separate layer on top.
- **No decap, no analog.** This is debug-probe and differential RE, so anything the config bitstream doesn't expose — analog-block internals (PLL VCO, RC-oscillator trim), hard-block gate-level RTL — isn't recoverable. It also isn't needed for the fabric, routing, clock, flash path, or MCU edge, which are all open and silicon-proven.

The one open frontier is packing density at scale: single dense structures run to 16 bits today, and the general dense-packing flow for the largest soft cores (SERV-scale) is the remaining piece. Its design — a dedicated nextpnr arch for the fabric — is in `docs/STATUS.md`.

## Repository layout

```text
agamemnon/          the toolchain package (pip install -e . → the `agamemnon` command)
  engine/             arch (nextpnr-generic adapter), bitgen, LZW codec, sel-encoding, physmap
  chipdb/             the AGRV2K device database (wires, pips, sel tables, silicon-verified conduction map)
  synth/              yosys: prims.v, cells_map.v, *.tcl
  openocd/            OpenOCD config (stock OpenOCD, no vendor "Supra")
  program.py          the flasher + SWD programmer (probe / sram / backup / flash / image)
  cli.py              the `agamemnon` command
mcu/                the RISC-V MCU SDK — ag32.h (memory map + peripheral regs) + linker script
examples/           blinky, loopback, firmware — each half, with build and flash steps
docs/               ARCHITECTURE · STATUS · HARDWARE_VALIDATION · BITSTREAM_FORMAT · PROGRAMMING · flashboot/
tests/              codec / lzw / edit-lut round-trips + the byte-exact build regression
```

## What's here, and what isn't

Here: the source, the `agamemnon` package, the synthesis scripts, the MCU SDK, examples, tests, and the recovered chip database itself, including the silicon-verified conduction map. It's clone-and-use, and it covers both halves of the chip — building the bitstream and flashing it.

Not here: the vendor binaries (`af.exe`, `Supra.exe`) or any vendor anything, and the Ghidra cache and RE tooling.

## How it was built

This isn't black-box bitstream diffing. AGM's tooling *contains* the architecture; AGaMEMnon extracts that data into open formats and checks each layer against `af.exe` byte-for-byte where it's a format, and on silicon where it's hardware. The one thing the vendor's data doesn't state — which edges physically conduct — was recovered by measuring the chip. Port the data that exists; measure the data that doesn't.

## Name

**AGaMEMnon.** Listen, I had "AG32" to work with, and something about "memory." Hardest problem in computer science. I named it before Nolan's *Odyssey* came out.

## Related documents

A writeup of how this works [is here](http://bbenchoff.com/pages/AGaMEMnon.html).
