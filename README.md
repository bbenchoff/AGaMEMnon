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
Verilog  →  yosys           open synthesis (RTL → AGRV2K LUT4/FF cells)
         →  nextpnr         open pack / place / route (the recovered AGRV2K device + our `agrv2k` uarch)
         →  agamemnon pack  open bitstream generation (routed design → logic.bin)
         →  agamemnon flash open programming (logic.bin → chip over SWD, CMSIS-DAP)
```

It's [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has heard of. Verilog synthesizes, places, routes, and runs on real silicon: combinational and sequential logic, counters and state machines, clocking across the array, output to real pins, and the RISC-V core reading and writing the fabric over its memory bus. There's a writeup of how it works [here](http://bbenchoff.com/pages/AGaMEMnon.html).

---

## Quick Start

```
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
pip install -e .
# Download oss-cad-suite and put it somewhere
export AGAMEMNON_OSS=/opt/oss-cad-suite
agamemmon build examples/designs/blink.v -o blink.bin
agamemmon flash blink.bin   # with a CMSIS-DAP probe attached
```

## Setup

Four things are needed to program the AG32:

* AGaMEMnon -- this repo, which ships the chip database
* open synthesis/place-and-route, which means yosys and nextpnr, [available here](https://github.com/yosyshq/oss-cad-suite-build)
* A RISC-V toolchain. This is simply `gcc-riscv64-unknown-elf`
* A CMSIS-DAP probe, if you're flashing over JTAG/OpenOCD. Currently, uploading over USB/Serial is a work in progress.


**1. The `agamemnon` package** — the chip database ships in the repo, so this is the whole install:

```bash
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
pip install -e .          # no download step; the recovered chipdb is in the tree
agamemnon --help
```

Python ≥ 3.8, standard library only. (`pip install pytest` if you want to run the test suite.)

**2. yosys + nextpnr** — the open front end (oss-cad-suite ships both). This place-and-route backend, `agrv2k`, **is not a separate tool** — it's a microarchitecture ("Viaduct" uarch) compiled *into* `nextpnr-generic` and selected with `nextpnr-generic --uarch agrv2k`. The binary is `nextpnr-generic` either way. The simplest source is [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build/releases) (prebuilt for Linux/macOS/Windows). Unpack it and either put its `bin/` on your `PATH` or point `$AGAMEMNON_OSS` at the top of it:

```bash
# Linux/macOS
export AGAMEMNON_OSS=/opt/oss-cad-suite          # or: source /opt/oss-cad-suite/environment
```
```powershell
# Windows (PowerShell)
$env:AGAMEMNON_OSS = "C:\oss-cad-suite"
```

`agamemnon build` finds `yosys` and `nextpnr-generic` there or on `PATH`. The AGRV2K device is *data* the package ships; stock nextpnr loads it (via the `arch.py` adapter `build` uses today), so no custom nextpnr build is needed to start. The `agrv2k` uarch is that same `nextpnr-generic` rebuilt with our C++ overlay (`build.sh` in `agamemnon/engine/uarch/agrv2k/`); it's in bring-up, so the stock-binary + `arch.py` path is the default for now.

**3. A RISC-V toolchain** — *only needed to build MCU firmware.* Any `riscv64-unknown-elf-gcc` will do (a distro `gcc-riscv64-unknown-elf`, or the `toolchain-agrv` gcc PlatformIO installs). Firmware links against the SRAM script in `mcu/` (see the examples).

**4. Programming hardware** — *only needed to flash or run on real silicon.* A CMSIS-DAP probe (the AGM DAP-Link on the dev board works) and an OpenOCD built with RISC-V-over-DAP support (`target create riscv -dap`). **oss-cad-suite's OpenOCD does not have this** — use a recent stock OpenOCD build. Point `agamemnon` at it if it isn't just `openocd` on your `PATH`:

```bash
export AGAMEMNON_OPENOCD=/usr/local/bin/openocd   # the shipped openocd/agrv2k.cfg is used automatically
```

There is no vendor driver anywhere in this: no "Supra" install, no `agrv` OpenOCD flash bank. The flasher talks to the on-chip flash controller directly.

## Using it

One `agamemnon` command drives both halves of the chip — the FPGA fabric and the flash/RISC-V side.

```bash
agamemnon build design.v -o design.bin                       # yosys → nextpnr-generic → bitgen
agamemnon flash design.bin --addr 0x80008100 --backup f.bin  # erase → program → verify
```

| `agamemnon …` | what it does |
|---|---|
| `build design.v` | Verilog → yosys → nextpnr (the shipped AGRV2K device) → bitstream `.bin` |
| `pack` / `unpack` | routed nextpnr JSON ↔ flashable `.bin` (icepack / iceunpack) |
| `decode` / `encode` / `edit-lut` | `.bin` ↔ 99,936-byte raw config image; open LUT editor |
| `probe` | read DEVICE_ID over SWD (expect `0x40200001`) |
| `sram fw -b fabric` | SRAM-inject a bitstream + firmware and run it (volatile, no flash write) |
| `flash bin --addr` | erase → program → verify; drives the flash controller directly, no vendor `agrv` driver |
| `image -b fabric -m fw` | assemble a combined boot image (fabric + MCU + config pointer) |
| `backup` | dump the whole 256 KB flash |

Useful build flags: `--leds` (pin outputs onto the board's LED pads), `--mcu` (enable the MCU↔fabric edge for GPIO/AHB designs), `--pin X10Y4_SLICE0` (constrain a cell), `--baseline foo.bin` (reuse a clock/preamble). Everything is overridable by environment (`AGAMEMNON_OSS`, `AGAMEMNON_OPENOCD`, `AGAMEMNON_DEVICE` for package selection, `AGAMEMNON_DATA`/`AGAMEMNON_ENGINE` to point at a different chipdb/engine); see `docs/USAGE.md`.

### Examples

`examples/` is clone-and-run. Offline — no hardware, just the front end:

```bash
agamemnon build examples/designs/comb.v -o comb.bin   # combinational: o = (a & b) | (c ^ d)
agamemnon build examples/designs/tff.v  -o tff.bin    # a toggle flip-flop (minimal sequential)
bash examples/01_roundtrip.sh                          # .bin → raw → .bin, byte-exact (LZW self-check)
bash examples/02_edit_lut.sh                           # open LUT editor: flip one LE's truth table
```

On silicon — a CMSIS-DAP probe and a board:

```bash
agamemnon probe                                        # → DEVICE_ID 0x40200001
agamemnon build examples/designs/mcu_loop2.v --mcu -o loop.bin       # MCU↔fabric GPIO loopback
agamemnon sram examples/firmware/looptest.bin -b loop.bin            # inject + run (volatile, SRAM)
agamemnon flash comb.bin --addr 0x80008100 --backup full.bin        # persist to flash (backup first)
```

`examples/designs/` holds the Verilog (combinational, toggle FF, the MCU↔fabric loopback `mcu_loop2.v`, and `ahb_pad.v` — an AHB-write slave whose register drives a header pin). `examples/firmware/` holds matching RISC-V stubs (loopback, AHB read/write, `ahb_blink.c` which blinks a pin from the CPU over the memory bus). `examples/loopback/` is the flash-boot-proven MCU↔fabric demo, with its own README. The RISC-V side (`mcu/ag32.h` + a linker script) builds with any `riscv64-unknown-elf-gcc`, and `agamemnon image` combines an MCU binary with a fabric bitstream into one flash image that self-boots.

## Repository layout

```text
agamemnon/          the toolchain package (pip install -e . → the `agamemnon` command)
  cli.py              the `agamemnon` command (build / pack / decode / edit-lut / probe / sram / flash / image)
  program.py          the open flasher + SWD programmer (drives the flash controller directly)
  engine/             the device→nextpnr adapter (arch.py) + our `agrv2k` nextpnr uarch (uarch/),
                        bitgen, LZW codec, sel-encoding, physmap, io_emit, MCU-edge + ring-pad paths
  chipdb/             the AGRV2K device database (wires, pips, sel tables, silicon-verified conduction map)
  synth/              yosys: prims.v, cells_map.v, *.tcl
  openocd/            OpenOCD config (stock OpenOCD, no vendor "Supra")
mcu/                the RISC-V MCU SDK — ag32.h (memory map + peripheral regs) + linker script
examples/           designs/ (Verilog) · firmware/ (RISC-V stubs) · loopback/ · runnable scripts
docs/               ARCHITECTURE · STATUS · HARDWARE_VALIDATION · BITSTREAM_FORMAT · PROGRAMMING · USAGE · flashboot/
tests/              codec / lzw / edit-lut round-trips + the byte-exact build regression
```

## How it was built

This is the product of a reverse engineering campaign of the vendor toolchain. Where this was inconclusive or non-existent, I probed the actual hardware.

This isn't black-box bitstream diffing. The official vendor tooling contains the architecture. This project extracted that data into open formats and checks each layer against the vendor tooling. It is byte-for-byte exact, and has been tested on silicon. The one thing the vendor's data doesn't state — which edges physically conduct — was recovered by measuring the chip.

**How it interacts with nextpnr.** The place-and-route is nextpnr, and the entire "AGRV2K-ness" is *data* — the recovered device graph (wires, bels, pips, the IO ring, clock spine, block RAM, MCU-edge crossings) handed to it. The clean way to feed nextpnr is our own microarchitecture, `agrv2k`, This is a Viaduct uarch that lives in `agamemnon/engine/uarch/agrv2k/`. 

### What runs on silicon

| Layer | Evidence |
|---|---|
| yosys synthesis (RTL → AGRV2K LUT4/FF) | builds |
| `.bin` LZW codec, both directions | byte-exact vs `af.exe` |
| Fabric-config CRC-32/BZIP2 | accepted by the chip's config engine |
| Physical map — 554,800 bits / 213 tiles, logic and routing | byte-exact |
| Open bitgen (routed design → `.bin`) | silicon; FCB accepts + activates (`STAT=0x000f0002`) |
| nextpnr pack / place / route on the shipped device (via the `arch.py` bootstrap) | silicon |
| Combinational logic · flip-flops | silicon; the inverter inverts, the FF toggles |
| Counters, shift registers, small FSMs, ripple adder | silicon; auto-placed, read back over AHB; dense counters to 16 bits |
| Clock distribution across the array | silicon; FFs clock at near and far tiles |
| Ring-pad output — fabric drives a real header pin | silicon; the pin toggles |
| MCU ↔ fabric GPIO — 4-bit loopback, auto-placed | silicon; 16/16 combinations |
| MCU AHB — CPU writes a fabric register, and the fabric drives it onto a pin | silicon; `*0x60000000 = v` captured; a CPU-driven pin blinks |
| MCU AHB — CPU reads fabric registers (`hrdata`) | silicon; multi-lane readback |
| Conduction + clock characterization | silicon-swept across the array |
| Flash-boot — our bitstream self-boots from flash, no debugger | silicon |
| Device / package awareness (L100 / L64 / L48 / Q32) | pin-legality gate; default AGRV2KL48, `AGAMEMNON_DEVICE` |

**Where it stops.** RE of the fabric configuration and the toolchain is done: Verilog goes to running silicon, both halves, no vendor binary. Two things are out of scope by nature. It optimizes for *correct, not fast* — it ships the vendor delay tables and designs run at a conservative clock; a timing-driven flow with real Fmax closure (an `icetime` analogue) would be a layer on top. And it's debug-probe and differential RE, so anything the config bitstream doesn't expose — analog-block internals (PLL VCO, RC-oscillator trim), hard-block gate-level RTL — isn't recoverable, and isn't needed for the fabric, routing, clock, flash path, or MCU edge, which are all open and silicon-proven. The one open frontier is packing density at scale: single dense structures run to 16 bits today, and the general dense-packing flow for the largest soft cores (SERV-scale) — a dedicated nextpnr arch for the fabric — is the remaining piece, sketched in `docs/STATUS.md`.

**Banked (silicon-diagnosed, intentionally deferred).** Two capabilities are built but parked because silicon testing found a hard limit, and neither blocks the SERV-scale goal:

- *Dedicated hardware carry chain (`Cin/Cout` ripple) for wide arithmetic.* The synth techmap, the uarch `pack_carries` fusion, and byte-exact `CFG_LUTCMUX` bitgen all work and route+bitgen a dense counter cleanly (0 unmapped). But on silicon the counter freezes: a ripple slice needs `pinC=Cin` (`modeMux=1`), which claims the C-mux, so the bit's own-Q feedback can't use the one conducting self-feedback path (`Qin → I[2]`) and is forced onto `I[1]`, whose crossbar *and* mesh routes are dead (verified across two tiles and both routings). Hardware `Cout` and a conducting own-Q can't share a slice on this fabric. The vendor manages it via a specific `RMUX→IMUX` hop we haven't characterized; closing it needs a connection-box conduction sweep or a per-slice vendor-route transplant. Wide arithmetic runs correctly via LUT+mesh carry instead — just not the vendor's fast path. Gated off (`AGRV2K_NO_FBBRIDGE`, `arch.py` `AGAMEMNON_HW_CARRY`).
- *Timing/Fmax closure* (above) — no analysis, conservative fixed clock.

SERV doesn't need either: it's bit-serial (no wide carry), and dense *packing* — the thing it does need — conducts on silicon (even-slot placement + `Qin` self-feedback; a 4-cell/one-tile design reads distinct values back over AHB). That dense-packing path is where the work continues.

## What's here, and what isn't

Here: the source, the `agamemnon` package, the synthesis scripts, the MCU SDK, examples, tests, and the recovered chip database itself, including the silicon-verified conduction map. It's clone-and-use, and it covers both halves of the chip — building the bitstream and flashing it.

Not here: the vendor binaries (`af.exe`, `Supra.exe`) or any vendor anything, and the Ghidra cache and RE tooling.

## Name

**AGaMEMnon.** Listen, I had "AG32" to work with, and something about "memory." Hardest problem in computer science. I named it before Nolan's *Odyssey* came out.

## Related documents

A writeup of how this works [is here](http://bbenchoff.com/pages/AGaMEMnon.html).


Two good questions — let me answer both straight.

Is the fabric just too constrained for SERV?

Largely, yes — and it's what I'd expect from this chip. The nuance:

- By raw count it fits: SERV synthesizes to ~1798 LUT4 / 1336 FF = 85% LUT / 63% FF. So it's not "doesn't fit."
- But 85% utilization is the problem, on this fabric. The AGRV2K has only 2112 LUT4 and — as this whole session showed — sparse routing: only a subset of pips physically conduct, the intra-tile crossbar is partly dead, and dense packing is genuinely hard. A design filling 85% of the LUTs demands very high routing utilization, and that's exactly where this fabric is weakest. Neither the placement nor the routing has headroom at that fill.
- The vendor tool failing corroborates it. af.exe choking on SERV's netlist strongly suggests AGM never targeted or validated designs anywhere near this size.

This is expected because the AGRV2K is a glue-logic eFPGA, not a soft-CPU host. It's a peripheral-augmentation block bolted onto the MCU — meant for state machines, protocol adapters, small accelerators at single-digit % utilization. 2112 LUT is tiny; SERV is the smallest RISC-V made (bit-serial, specifically to fit tiny FPGAs) and it's still at 85% here. So: full SERV is right at or past the practical edge of this part. A reduced SERV (minimal config — no CSR/MDU/compressed, smaller register file) at ~50-60% util would have far better odds, both for placement headroom and routing. That's the realistic "soft core on the AG32" target, not the full servant SoC.

Open toolchain status

The open flow is broad and silicon-proven — most of the chip is done:

┌──────────────────────────────────────────────────────────────┬─────┐
│                      Working on silicon                      │     │
├──────────────────────────────────────────────────────────────┼─────┤
│ Verilog → yosys → nextpnr → open bitgen → flash → boot       │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Combinational, flip-flops, clocking (near + far tiles)       │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Counters / shift / FSM / adder (dense to ~16 bits)           │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Multi-bit sequential through the agrv2k uarch (this session) │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ MCU↔fabric GPIO loopback, AHB write and read                 │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Ring-pad output (PIN_18 toggles; MCU-controlled blink)       │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ BRAM (config, dynamic ROM read, $mem techmap) + PLL          │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Flash-boot (self-boots our bitstream, no debugger)           │ ✅  │
├──────────────────────────────────────────────────────────────┼─────┤
│ Byte-exact .bin codec / physmap / conduction+clock sweep     │ ✅  │
└──────────────────────────────────────────────────────────────┴─────┘

Remaining open tasks (honest, prioritized)

1. Dense-at-scale / soft core — the big one, now well-characterized: the conduction-aware placer caps ~10–15 cells; needs a scalable placer (analytical/force-directed + conduction refinement). Realistic target = a reduced soft core, not full SERV.
2. cli.py → uarch integration — the shipping agamemnon build still uses the old arch.py + Python-hook flow; the new uarch (with the conduction-gated device + placer) isn't wired into the CLI yet. Mechanical but not done.
3. BRAM bel promotion — the $mem→BRAM techmap works, but the BRAM bel isn't in the clean arch/uarch as a first-class placeable.
4. Wide-design verification / readout observability — polled AHB read can't sweep periods beyond ~256 cycles; a deterministic clock-gated readout would make wide designs airtight.
5. Pad-output over distance — a self-contained fast fabric blink on the on-board LEDs is still blocked by conduction-over-distance (the MCU-mediated blink works around it).
6. The tail — ~1% routing-coverage edges; timing/Fmax closure (intentionally out of scope — it's a correct-not-fast flow); a few probe-less transport niceties.

Net: the toolchain is a genuinely complete open Verilog→silicon flow for the chip's intended scale (glue logic, peripherals, small sequential designs, MCU-edge). The one true frontier is packing a large design densely — and that turns out to be near the fabric's physical edge, which is why neither our tools nor AGM's get there.
