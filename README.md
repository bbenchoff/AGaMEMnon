# Project AGaMEMnon

**A complete, fully open bitstream and place-and-route toolchain for the AGM AG32 / AGRV2K embedded FPGA fabric.**

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

This fabric is the configurable glue that attaches almost any pin to any peripheral. You can route a UART to almost any pin, drop a state machine into a signal path, add a custom peripheral next to the CPU, mux at runtime, and have it all configure from SPI flash at boot. That makes the AG32 unusually good for flexible pin assignment, protocol glue, deterministic IO, and small custom hardware without a separate FPGA. Think of it as a Cypress PSoC, except the programmable part is an actual FPGA bolted to a RISC-V core.

The AG32 has almost no English-language documentation. The sanctioned way to build a bitstream is a Windows-only Altera Quartus II fork you fetch from a Baidu Netdisk link (password `12ej`), driving a black-box fabric back-end, `af.exe`. There is no Linux path and no open format. Fuck you if you want to use this chip as intended.

*Project AGaMEMnon* takes Verilog and produces a flashable AG32 fabric bitstream. Synthesis, pack, place, route, bitstream generation, and programming, with no proprietary vendor binary anywhere in the path, are supported:

```text
Verilog  →  yosys            open synthesis (RTL → AGRV2K LUT4/FF cells)
         →  nextpnr-generic  open pack / place / route (stock nextpnr + the shipped AGRV2K arch)
         →  agamemnon pack   open bitstream generation (routed design → logic.bin)
         →  agamemnon flash  open programming (logic.bin → chip over SWD, CMSIS-DAP)
```

This is [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has heard of. Arbitrary Verilog synthesizes, places, routes, and *runs on real silicon*: combinational and sequential logic, counters and state machines, clocking across the whole array, output to real pins, and the RISC-V core reading and writing the fabric over its memory bus — all from an open toolchain with no vendor binary anywhere in the path. A blog page about how this works and how I did it [is here](http://bbenchoff.com/pages/AGaMEMnon.html).

---

## What it does

One `agamemnon` command drives **both halves of the chip** -- the FPGA fabric and the flash/RISC-V side -- with no vendor tooling. No `af.exe`, no Quartus, no Windows, no Baidu, and no vendor OpenOCD driver. `agamemnon build design.v -o design.bin` takes Verilog through synth → place & route → bitstream; `agamemnon flash design.bin --addr 0x80008100` writes it to the chip over SWD; and there's a from-scratch RISC-V MCU SDK in `mcu/`. The FPGA flow mirrors IceStorm one-for-one, so if you know that flow you already know this one:

| `agamemnon …` | what it does |
|---|---|
| `build design.v` | Verilog → yosys → **nextpnr-generic** (with the shipped AGRV2K arch) → bitstream `.bin` (the whole FPGA flow) |
| `pack` / `unpack` | routed nextpnr JSON ↔ flashable `.bin` (icepack / iceunpack) |
| `decode` / `encode` / `edit-lut` | `.bin` ↔ 99,936-byte raw config image; open LUT editor |
| `probe` | read DEVICE_ID over SWD (expect `0x40200001`) |
| `sram fw -b fabric` | SRAM-inject a bitstream + firmware and run it (volatile, no flash) |
| `flash bin --addr` | erase → program → verify to flash — the **open flasher**, drives the flash controller directly (no vendor `agrv` driver) |
| `image -b fabric -m fw` | assemble a combined boot image (fabric + MCU + config pointer) |
| `backup` | dump the whole 256 KB flash |

```bash
pip install -e .                                             # chip database ships with the repo — clone and go
agamemnon build design.v -o design.bin                       # yosys → nextpnr-generic → bitgen
agamemnon flash design.bin --addr 0x80008100 --backup f.bin  # open flasher: erase → program → verify
```

The RISC-V side (`mcu/ag32.h` + a linker script) builds with any `riscv64-unknown-elf-gcc`, and `agamemnon image` combines an MCU binary with a fabric bitstream into one flash image that self-boots.

## Coverage — what runs on real silicon

Every entry below is validated byte-for-byte against `af.exe` where it's a format claim, and on real AG32 silicon where it's a hardware claim (`DEVICE_ID 0x40200001`, RISC-V `misa 0x40801125`).

| Layer | Status |
|---|---|
| yosys synthesis (RTL → AGRV2K LUT4/FF) | ✅ Works |
| `.bin` LZW codec, both directions, byte-exact | ✅ Works |
| Fabric-config CRC-32/BZIP2 (checked by the chip's config engine) | ✅ Works (silicon) |
| Full physical map — 554,800 bits / 213 tiles, logic *and* routing | ✅ Works |
| Open bitgen (routed design → `.bin`), accepted + activated by the FCB | ✅ Works (silicon, `STAT=0x000f0002`) |
| nextpnr-generic pack / place / route on the genuine chip database | ✅ Works (silicon) |
| Combinational logic computing on silicon | ✅ Works (inverter inverts) |
| Sequential logic — flip-flops on silicon | ✅ Works (FF toggles) |
| Multi-bit counters / arbitrary sequential logic | ✅ Works (silicon; carry chains count, auto-placed) |
| **Clock distribution across the whole array | ✅ Works (silicon; FFs clock at near *and* far tiles) |
| Ring-pad OUTPUT — fabric drives a real external header pin** | ✅ Works (silicon; pin toggles) |
| MCU ↔ fabric GPIO — 4-bit loopback, auto-placed | ✅ Works (16/16 combos) |
| MCU AHB memory bus — CPU writes a fabric register | ✅ Works (silicon, `*0x60000000 = v` → captured) |
| MCU AHB memory bus — CPU reads a fabric register (`hrdata`) | ✅ Works (silicon; read returns exactly what the fabric drives) |
| Full-device conduction + clock characterization | ✅ Complete (silicon-swept; the device model is truthful) |
| Arbitrary designs place + route + run | ✅ Works (silicon; the router only ever picks edges silicon says conduct) |
| Flash-boot — our open bitstream self-boots from flash, no debugger in the loop | ✅ Works (silicon) |
| Device / package awareness (L100 / L64 / L48 / Q32) | ✅ Works (pin legality gate; default AGRV2KL48, `AGAMEMNON_DEVICE`) |

### How the last mile closed — a truthful device model

An open FPGA toolchain is only as good as its device model. nextpnr places and routes perfectly *against the arch it's given* — so the whole game is handing it an arch that matches the silicon. For the AGRV2K, the hard part isn't the config format (that's format RE, and it's byte-exact). It's that **which fabric edges electrically conduct, and which tiles the clock actually reaches, is not written down anywhere** — the vendor tool computes it per-design inside its router, and it isn't extractable at rest.

So AGaMEMnon builds that model the only way it can be built: it turns the chip into its own characterization oracle. An automated silicon sweep forces a signal through every tile and path and *measures what actually conducts and clocks*, accumulating a silicon-verified conduction map. The arch is then gated on that map, so nextpnr is physically incapable of choosing an edge that doesn't work — dead intra-tile carries are excluded (so counters auto-spread onto conducting routes), non-clocking placements aren't offered, and far-tile routing uses only paths proven on silicon. That's the difference between "~99% and a grind" and *done*: arbitrary RTL routes and runs, automatically, because the model tells the truth.

## Honest boundaries — where "complete" ends

Complete RE of the fabric configuration and the toolchain is the achievable goal, and it's done: arbitrary Verilog goes to running silicon, both halves, no vendor binary. Two honest edges remain, by nature rather than by gap:

- **Function, not Fmax.** This is not [icetime](https://github.com/YosysHQ/icestorm/tree/main/icetime), and I have no idea how to do that. This ships the vendor delay tables. The flow optimizes for *correct*, not *fast*. A timing-driven placer/router with real Fmax closure (`agamemnon time`) is a distinct optimization layer, not a correctness gap — designs run at a conservative clock today.
- **No decap, no analog.** This is debug-probe + differential RE. We cannot recover analog-block internals (PLL VCO, RC-oscillator trim) or the hard-block gate-level RTL — nothing the config bitstream doesn't expose. It doesn't need to: the fabric, the routing, the clock, the flash path, and the MCU edge are all open and silicon-proven.

## What's next (all additive — none of it blocks use)

- **`.agasc` ASCII hub** — a human-readable per-tile config text (the `icebox` equivalent) that makes the bitstream self-documenting and unlocks `time` / `bram` / `vlog` for free.
- **Wider MCU bus** — 32-bit AHB read/write in one shot (single-bit read/write are silicon-proven; widening is more of the same FFs, auto-spread).
- **Probe-less flash transports** — UART / native-USB-DFU loaders so you don't even need a CMSIS-DAP probe.

## Repository layout

```text
agamemnon/          the toolchain package (pip install -e . → the `agamemnon` command)
  engine/             the FPGA engine — arch (nextpnr-generic adapter) · bitgen · LZW codec · sel-encoding · physmap
  chipdb/             the shipped AGRV2K device database (wires, pips, sel tables, silicon-verified conduction map)
  synth/              yosys: prims.v, cells_map.v, *.tcl
  openocd/            the open OpenOCD config (stock OpenOCD, no vendor "Supra")
  program.py          the open flasher + SWD programmer (probe / sram / backup / flash / image)
  cli.py              the `agamemnon` command
mcu/                the RISC-V MCU SDK — ag32.h (memory map + peripheral regs) + linker script
examples/           blinky, loopback, firmware — each half + how to build & flash it
docs/               ARCHITECTURE · STATUS · HARDWARE_VALIDATION · BITSTREAM_FORMAT · PROGRAMMING · flashboot/
tests/              codec / lzw / edit-lut round-trips + the byte-exact build regression
```

## What's here, and what isn't.

What's here: Source, the `agamemnon` package, the synthesis scripts, the MCU SDK, examples, tests, and the recovered chip database itself — including the silicon-verified conduction map — so the repo is genuinely clone-and-use, and it covers both halves of the chip (build the bitstream *and* flash it).

What's not here: the vendor binaries (`af.exe`, `Supra.exe`), or any vendor _anything_. The Ghidra cache and the reverse-engineering tooling are also not here.

## Philosophy

This is not a black-box statistical bitstream-diffing campaign. AGM's vendor tooling *contains* the architecture; AGaMEMnon extracts and translates that knowledge into open formats, validating each layer against `af.exe` byte-for-byte wherever possible and on real silicon wherever it matters. Where the vendor's knowledge lives only inside its running router — which fabric edges physically conduct — we recovered it the honest way: by measuring the chip itself. This isn't "reverse-engineer a black box," it's "port the vendor's data into open formats, and measure what the data won't tell you."

## Name

**AGaMEMnon.** Listen, I had "AG32" to work with, and something about "memory." Hardest problem in computer science. I named it before Nolan's *Odyssey* came out.

## Related documents

A blog page about how this works [is here](http://bbenchoff.com/pages/AGaMEMnon.html).
