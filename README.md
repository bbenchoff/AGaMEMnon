# Project AGaMEMnon

**A fully open bitstream and place-and-route toolchain for the AGM AG32 / AGRV2K embedded FPGA fabric.**

The [AG32](https://www.agm-micro.com/) is not quite a microcontroller and not quite a normal FPGA. It's a real RV32IMAFC core with hard peripherals (UART, SPI, I²C, CAN, USB, Ethernet MAC, timers, ADC/DAC, GPIO), _plus_ a small programmable fabric sitting between those peripherals and the pins:

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

This fabric is the configurable glue that attaches almost any pin to any peripheral. You can route a UART to almost any pin, drop a state machine into a signal path, add a custom peripheral next to the CPU, mux at runtime, and have it all configure from SPI flash at boot. That makes the AG32 unusually good for flexible pin assignment, protocol glue, deterministic IO, and small custom hardware without a separate FPGA. Think of it as a Cypress PSoC, except the programmable part is an actual FPGA bolted to a RISC-V core.

The AG32 has almost no English-language documentation. The sanctioned way to build a bitstream is a Windows-only Altera Quartus II fork you fetch from a Baidu Netdisk link (password `12ej`), driving a black-box fabric back-end, `af.exe`. There is no Linux path and no open format. Fuck you if you want to use this chip as intended.

*Project AGaMEMnon* takes Verilog and produces a flashable AG32 fabric bitstream — synthesis, pack, place, route, bitstream generation, and programming — with no proprietary vendor binary anywhere in the path:

```text
Verilog  →  yosys            open synthesis (RTL → AGRV2K LUT4/FF cells)
         →  nextpnr-generic  open pack / place / route (stock nextpnr + the shipped AGRV2K arch)
         →  agamemnon pack   open bitstream generation (routed design → logic.bin)
         →  agamemnon flash  open programming (logic.bin → chip over SWD, CMSIS-DAP)
```

This is [IceStorm](https://github.com/YosysHQ/icestorm) for a chip nobody has heard of.

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

## Coverage — what runs on real silicon today

Every entry below is validated byte-for-byte against `af.exe` where it's a format claim, and on real AG32 silicon where it's a hardware claim (the *(silicon)* rows; `DEVICE_ID 0x40200001`, RISC-V `misa 0x40801125`).

| Layer | Status |
|---|---|
| yosys synthesis (RTL → AGRV2K LUT4/FF) | Works |
| `.bin` LZW codec, both directions, byte-exact | Works |
| Fabric-config CRC-32/BZIP2 (checked by the chip's config engine) | Works (silicon) |
| Full physical map — 554,800 bits / 213 tiles, logic *and* routing | Works |
| Open bitgen (routed design → `.bin`), accepted + activated by the FCB | Works (silicon, `STAT=0x000f0002`) |
| nextpnr-generic pack/place/route on the genuine chip database | Works |
| Combinational logic computing on silicon | Works (inverter inverts) |
| Sequential logic on silicon | Works (flip-flop toggles) |
| MCU ↔ fabric GPIO — 4-bit loopback, auto-placed | Works (16/16 combos) |
| MCU AHB memory bus — CPU writes a fabric register | Works (silicon, `*0x60000000 = v` → readback) |
| General clock distribution | Works (silicon; FFs clock at scattered near *and* far tiles) |
| Far-tile MCU-dout readback (genuinely-far FF → MCU GPIO) | Silicon-proven on **3 of 4** dout bits via a per-exit live-feeder whitelist; the 4th exit (`RMUX02`/bit 6) is local-only. Dense far-tile coverage is still a grind |
| Device / package awareness (L100 / L64 / L48 / Q32) | Pin-NUMBER legality gate — rejects a design declaring a `PIN_n` the package doesn't bond; default AGRV2KL48 (`AGAMEMNON_DEVICE`). Per-package *physical* pad pruning is a documented follow-up (needs the `PIN_n→pad` bond map from `af.exe`) |
| Flash-boot — our open bitstream self-boots from flash, no debugger in the loop | Works (silicon) |
| Routing byte-exactness | ~99% (FP=0) — never emits *wrong* bits; the tail is dense-crossbar + far-tile *coverage*, not error |

The one honest frontier is that last row: on a large, congested design the router can still hit a pip we can't yet encode byte-exactly, so it either takes an approximate encoding (~98% likely correct) or leaves the net unmapped. Small and medium designs are reliable; closing the tail is a coverage grind, not a mystery.

## Roadmap

- **Routing to byte-exact / full coverage** — grow the observed-real routing corpus and promote the remaining approximate sel-encodings to proven closed forms, so *any* design that routes is guaranteed electrically correct. (Highest leverage; it gates dense designs and far-tile clocking.)
- **`agamemnon time`** — a real timing model. We have the vendor's delay tables in the arch DB, but a timing-driven placer/router (Fmax closure) is a substantial piece we haven't built. Today the flow optimizes for *function*, not *frequency*.
- **Wide bels** — the full IO ring, all four BRAM ports, and arbitrary PLL clocks. The IO/PLL/BRAM encoders are already cracked and reproduce vendor output byte-exact; what remains is general nextpnr integration, not RE.
- **Wider MCU bus** — 32-bit AHB and the read path (the write path is silicon-proven).
- **`.agasc` ASCII hub** — a human-readable per-tile config text (the `icebox` equivalent), which makes the bitstream self-documenting and unlocks `time` / `bram` / `vlog` for free.
- **Persistent flash-boot polish** — the open flasher (erase/program) is silicon-proven; what's left is confirming the option-byte write sequence (via differential capture) and a power-cycle test of an uncompressed image assembled by `agamemnon image`, so `build → image → flash → self-boot` is one verified path. Also on deck: UART / native-USB-DFU flash transports (no probe needed).

## Honest boundaries — where "complete" ends

This is debug-probe + differential RE, not decap. We cannot recover analog blocks (PLL VCO internals, RC-oscillator trim), the hard-block gate-level RTL, or anything the config bitstream doesn't expose — complete RE of the fabric configuration and toolchain is the achievable goal, and it's done.Timing optimization is the fuzzy frontier (see roadmap). Un-exercised corners stay honest-unknown until a design drives them, and each is crackable the same way.

## Repository layout

```text
agamemnon/          the toolchain package (pip install -e . → the `agamemnon` command)
  engine/             the FPGA engine — arch (nextpnr-generic adapter) · bitgen · LZW codec · sel-encoding · physmap
  chipdb/             the shipped AGRV2K device database (wires, pips, sel tables, …)
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

What's here: Source, the `agamemnon` package, the synthesis scripts, the MCU SDK, examples, tests, and the recovered chip database itself — so the repo is genuinely clone-and-use, and it covers both halves of the chip (build the bitstream *and* flash it).

What's not here: the vendor binaries (`af.exe`, `Supra.exe`), or any vendor _anything_. The Ghidra cache, and the reverse-engineering tooling are also not here.

## Philosophy

This is not a black-box statistical bitstream-diffing campaign. AGM's vendor tooling *contains* the architecture; AGaMEMnon extracts and translates that knowledge into open formats, validating each layer against `af.exe` byte-for-byte wherever possible and on real silicon wherever it matters. This isn't a "reverse-engineer a black box", it's a "port the vendor's data into open formats" project.

## Name

**AGaMEMnon.** Listen, I had "AG32" to work with, and something about "memory." Hardest problem in computer science. I named it before Nolan's *Odyssey* came out.

## Related documents

A blog page about how this works [is here](http://bbenchoff.com/pages/AGaMEMnon.html).
