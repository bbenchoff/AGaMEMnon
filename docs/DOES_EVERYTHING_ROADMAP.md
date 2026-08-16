# The "does-everything" roadmap — from today's L48 subset to full vendor parity + a completely-open AG32

> The durable goal map. It answers one question: **what stands between today's
> fail-closed L48 tool and a toolchain that (a) builds anything the vendor
> Quartus-fork/`af.exe` flow can build and (b) generates every configuration bit
> from scratch with no vendor artifact in the tree?**
>
> This page is a *plan*, not a claim. Nothing here widens the supported surface.
> The authoritative statements of what is supported today remain
> [STATUS.md](STATUS.md), [VENDOR_PARITY.md](VENDOR_PARITY.md), and the generated
> [FPGA_PARITY_LEDGER.md](FPGA_PARITY_LEDGER.md); the config-surface partition is
> [CONFIG_SURFACE_MAP.md](CONFIG_SURFACE_MAP.md); the canvas anatomy is
> [FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md); the peripheral surface is
> [PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md); the MCU-edge worklist is
> [MCU_FABRIC_ROADMAP.md](MCU_FABRIC_ROADMAP.md); the ordered near-term board work
> is [../ROADMAP.md](../ROADMAP.md). Where this page and those disagree on *state*,
> they are right and this is stale.

## How to read this

Every remaining gap is tagged with **the kind of work that closes it**, because
that determines who can do it and what it costs:

- **DECODE** — desk reverse-engineering. Extend the arch DB / decode tables so
  the open flow both *knows* and can *emit* a bit-family. No board required to
  make progress; a silicon boot usually gates the final promotion. Most DECODE
  work happens in the sibling `../AG32-Docs` workbench and is promoted by hand.
- **SILICON** — board qualification on the attached AG32VF303CCT6 L48. The
  encoding may already be known; what is missing is an electrically observable
  oracle that proves *behaviour*, not just config acceptance.
- **BENCH-gated** — needs external hardware the qualification bench does not
  have: a CAN transceiver, an Ethernet PHY, a USB host, an analog fixture, a
  32 kHz/LSE or 12/16 MHz HSE source, or a non-L48 package board.
- **TOOLCHAIN** — P&R, CLI, engine, scale, and robustness work. No new device
  knowledge; better software around the knowledge we have.

**Leverage** = how much "does-everything / vendor parity" one unit of work
unlocks, discounted by tractability and by whether it *unblocks other work*. The
three biggest levers are structural: one decode that closes two headline gaps at
once, and two pipelines that convert hand experiments into mass production.

### The one structural insight that orders everything

From [CONFIG_SURFACE_MAP.md](CONFIG_SURFACE_MAP.md): the 99,936-byte config image
is three planes — **LUT function** (decoded), **routing/cell interconnect**
(~26% named), and **subsystem/peripheral** (partly decoded). The consequence:

> **"Completely open" and "routing vendor parity" are the same decode viewed two
> ways.** The unmapped ~74% of the routing plane is *both* the reason the vendor
> canvas cannot yet be generated from scratch *and* the reason arbitrary vendor
> routes are not yet emittable. Decode the per-LogicTile crossbar bit-line map
> once and you retire the canvas *and* complete routing-bit parity.

You can measure the gap yourself, offline, with the shipped tools:
[`examples/bitstream_provenance.py`](../examples/bitstream_provenance.py) prints
the named-vs-unmapped split (today: 1,460 named / 230,116 unmapped set bits) and
the byte-exact round-trip. Driving `unknown_set_bits` toward zero is the
canvas-retirement metric.

## Top-5 ranked next actions

1. **Promote the crossbar bit-line -> {resource, reset-polarity} map and add a
   from-scratch base-image emitter.** *(DECODE -> SILICON.)* The decoded
   `alta_tile_agr_cfg`-class table already exists in the `../AG32-Docs` workbench;
   promote it clean, extend `default_frame` to fill the reserved routing/seam
   region from the tile grid, gate the generated base **byte-exact** against
   `fabric_default.bin`, then boot a generated base on silicon and delete the
   canvas. **Status: the decode and silicon parts are done** — the generated base
   is 100% byte-exact and configures on silicon, and designs on either base are
   bit-identical. What is left is the packaging step: flip the default and delete
   the file. **Why it still mattered:** it closes *both* the from-scratch image
   ("completely open") and routing-bit parity, and it unblocks routing
   closure (action 3). See
   [FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md).

2. **Stand up the self-hosted HIL instrument + nightly hardware-in-the-loop CI.**
   *(TOOLCHAIN + SILICON.)* The External-AHB register bank is already qualified;
   turn it into a firmware-reported oracle that walks the parity matrix (routing
   conduction, BRAM modes, carry corridors, clocking state) and appends
   machine-generated evidence under the same hash discipline as hand runs; keep
   pad-electrical claims on the Pico probe path. **Why #2:** corridor-at-a-time
   qualification costs ~one bench session per corridor and the parity surface is
   tens of thousands of corridors — this changes the cost structure of *every*
   SILICON gap below. Prerequisite (the register-bank instrument) is done; the
   unchecked steps are the firmware oracle and the nightly sweep
   ([../ROADMAP.md](../ROADMAP.md) "Technique 2").

3. **Finish the differential `af.exe` pipeline and admit routing at
   population scale.** *(TOOLCHAIN + DECODE -> SILICON.)* The harness, constrained
   netlist generation, ownership-attributed diffing, and candidate store are
   built; the open items are silicon-arbitrating divergences, refeeding the
   74,103 conflicted + 2,393 zero-selector keys, and admitting reviewed
   population rows under the approved dossier/holdout/exception gates. **Why #3:**
   it is the only path from a corpus-shaped baseline (a clean edge in just
   159/322 grid tiles) to device-scale routing — i.e. "any design the vendor can
   route." Depends on actions 1 and 2 for prediction and cheap arbitration.

4. **Decode and qualify the MCU clock/PLL/oscillator programming model, then
   generalize PLL past the seven fixed profiles.** *(DECODE -> SILICON, partly
   BENCH-gated.)* Recover the RCC source-select + PLL-multiplier encoding, expose
   a bounded setter with HSI fallback, and add arbitrary legal dividers,
   phase/duty, feedback/bypass, other outputs, and HSI/HSE/OSC source selection.
   **Why #4:** a precise, switchable clock is the prerequisite for real UART
   baud, ADC/DAC sample rates, and the USB 60 MHz point — it gates the whole
   peripheral program — and it closes the clock plane. `(100,16)`/`(100,12)` need
   16/12 MHz-HSE boards (BENCH). See [PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md)
   and [MCU_CLOCKS.md](MCU_CLOCKS.md).

5. **Bring the analog subsystem into the open flow (ADC / DAC / comparator).**
   *(DECODE + BENCH.)* Register models, open drivers, and a bench run now exist:
   ADC0/1/2 one-shot, DAC0/1 static output and CMP0 unit 1 were observed on L48
   over the `0x60000000` window. **But that ran on a fabric image instantiating
   the vendor `analog_ip` hard-macro, which AGaMEMnon's bitgen does not emit**, and
   none of it is in an append-only ledger. So the remaining work is: make the open
   flow emit the analog IP; bank the observations as evidence; extend fabric routes
   beyond the read-only ADC0 lanes; explain why external ADC channels 0-3 read
   full scale (**cause unestablished**); resolve CMP0 unit 2 (unproven, reads high
   at every code); and determine ownership/reset/idle before driving an analog
   input. **Why #5:** it is the most-requested "does-everything" capability the
   chip advertises, and it is the one peripheral whose *open emission* is still
   missing rather than merely unqualified. See
   [ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) and the ranked gaps in
   [PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md).

## The full gap ledger

Ranked by leverage. "Class" is the dominant kind of work; most gaps need a
DECODE step then a SILICON gate.

| # | Gap | Class | Today | Concrete next action |
|---|---|---|---|---|
| 1 | From-scratch bitstream / canvas retirement (plane 2) | DONE (2026-08-14) except one honest unknown | the from-scratch base is the **default** for every build (release / individually_qualified; `qualification/fabric_base_evidence.jsonl`), designs on either base are bit-identical across the retained pack corpus, and the generated image configures on silicon (`FCB_STAT = 0x000f0002`); the canvas ships only as a non-loadable decode reference and differential anchor | name the *function* of the unnamed reserved bit-lines and 15 `XXXX` spares (position and reset value are reproduced today) |
| 2 | Mass-qualification infrastructure | TOOLCHAIN + SILICON | register-bank instrument qualified; hand runs only | firmware-reported oracle over External-AHB; nightly HIL CI appending hashed evidence |
| 3 | Routing parity & closure (plane 2) | TOOLCHAIN + DECODE -> SILICON | clean edge in 159/322 tiles; 6 RMUX30 rows admitted; 90% of a corpus slice | silicon-arbitrate divergences; refeed conflicted/zero keys; predict the 163 uncovered tiles; admit population rows via the dossier gates; track % destination-mux coverage |
| 4 | Full PLL / clock plane | DECODE -> SILICON (+ BENCH) | fabric side is broad: 45 admitted `(SYSCLK,HSE)` ratios, 43 silicon-frequency-qualified rows spanning HSE=8 `SYSCLK` 4-248 MHz. The **MCU** clock tree is the gap: only UART0's reference (~14.47 MHz) and MTIME (14.08 MHz) are measured, SPI0's reference is unresolved, and its divider has no observable effect | recover the RCC clock-switch + PLL model; measure each peripheral domain; fix the SPI divider defect; arbitrary dividers/phase/duty/feedback/bypass/outputs; HSI/OSC sources; 16/12 MHz-HSE boards for `(100,16)/(100,12)` |
| 5 | Peripheral plane — analog (ADC/DAC/comparator) | DECODE + BENCH | drivers ship and a one-shot/static subset is observed on the bench, but only through the **vendor `analog_ip` macro the open flow cannot emit**, and with no ledger row; ADC0 read-only route fragments only; CMP0 unit 2 unproven; external ADC ch0-3 read full scale for reasons **not established** | make the open flow emit the analog IP; bank the bench results into a ledger; resolve CMP0 unit 2 and the ch0-3 cause; cover DMA/continuous-scan |
| 6 | Peripheral plane — hard MMIO breadth | DECODE + SILICON + BENCH | 9 blocks silicon-qualified (incl. UART0 pad TX, I2C0 and SPI0 transmit framing); receive paths, bit rates, SPI1/I2C1/UART1-4 open; CAN has register activity but **no bits on a wire** and no ledger row | typed drivers + non-destructive evidence per block; CAN/Ethernet/USB-host need a transceiver/PHY/host (BENCH); RTC/IWDG need an LSI/LSE clock (BENCH) |
| 7 | MCU External-AHB slave breadth | DECODE -> SILICON | complete-byte public bank; exact 16-bit held-scratch checkpoint; 32-bit reads on the byte bank; aligned byte/half on the byte bank; SINGLE only | 16-bit address/subword/public-bank integration; hard `MCU_RESETN`; alternate/PLL3 bus clocks; generic direct-D lowering; full protocol modes |
| 8 | Fabric AHB master | DECODE -> SILICON | no route/qualification | route request/addr/data; read-only reserved-SRAM first, then canaried writes; bounded timeout + error reporting |
| 9 | BRAM modes / sites | DECODE -> SILICON | X13Y4 read subset (x18 A, x2 B, x9 bundle, 1024-word addr); 39 config rows experimental (config surface X13Y1..Y4, placement surface X13Y4 only); PORTA_OUTREG and bounded x2 PORTB_OUTREG each measured at exactly one read clock; PACKEDMODE has a first-order effect with mechanism unknown; CLKMODE is a bounded null across three compositions | broader writes and broader dual-port operation, other-mode output-register behaviour, byte enables, width/mode composition, independent clocks, collision/RDW, high-address breadth, sites beyond X13Y4, most B4 rows |
| 10 | IO electrical / OE / packages | DECODE + SILICON + BENCH | L48 static in/out; recovered L48/Q32/L64/L100 maps; drive-current table decoded | qualify dynamic OE/open-drain/bidirectional + drive/pull electrical on L48; then Q32, L64, L100 on package boards (BENCH) |
| 11 | Scale / bigger designs | TOOLCHAIN | SERV-scale replay; small fresh placements | make the `agrv2k` Viaduct placer/router close larger fresh designs; conduction-gated graph at scale; congestion + timing-aware placement |
| 12 | Dedicated carry breadth | DECODE -> SILICON | same-tile chains + one 33-site corridor | arbitrary seed/spill corridors, multi-chain placement, all carry sites/modes |
| 13 | Native timing sign-off | DECODE + SILICON + BENCH | 542 exact local pairs over 9,375 pips; conservative fallback on 226,540 | native wire/skew/IO/BRAM/hard-block models; package + PVT; Fmax equivalence to the vendor report |
| 14 | DMA sidebands + `EXT_INT0..7` | DECODE -> SILICON | request/response route smokes; unconnected hypotheses | derive request/clear/TC polarity/timing; route >=2 independent requests; qualify one `EXT_INTx` fabric source |
| 15 | SERV / RV32I compliance | TOOLCHAIN + SILICON | retained instruction-signature subset | R-type ADD, CSRs, exceptions/traps/interrupts, general fresh-source closure |
| 16 | SDK breadth (RTL + MCU) | TOOLCHAIN | bounded primitive/parameter surface; core MCU drivers | broaden the vendor primitive/parameter library lowering; open drivers for RTC/flash/CAN/USB/ADC/DAC/comparators/Ethernet |
| 17 | Boot / deployment / transports | SILICON + BENCH | existing-pointer boot; SRAM + flash backup/verify | from-scratch boot image on blank/restored device; option-pointer programming with staged recovery; qualify Pico UART + USB-CDC transports end-to-end |

## Detail by gap

### 1 & 3 — the routing plane (canvas + parity are one decode)

The reserved routing/seam SRAM default (227,652 bits) is the single biggest
blocker to a from-scratch image; the *same* undecoded bit-lines are the ~74% of
the interconnect plane the flow cannot yet emit for arbitrary vendor routes. The
work is: (a) promote the per-LogicTile crossbar bit-line map (a by-hand,
leak-audited `AG32-Docs -> AGaMEMnon` promotion); (b) give every bit-line a
`{resource, reset-polarity}`; (c) emit the reserved region declaratively the way
the preamble already is; (d) gate the generated base byte-exact against the
canvas; (e) prove it boots. With the map in hand, routing closure uses the
tile-relative selector scheme to predict encodings for the 163 uncovered tiles,
validated through the differential harness and the HIL instrument rather than
shipped as prediction. Track closure as **percent of destination-mux coverage**,
not as a feature list.

### 2 — mass qualification is the rate limiter

[../ROADMAP.md](../ROADMAP.md) states plainly that corridor-at-a-time
qualification *cannot finish* the parity surface. Two pipelines fix the economics
and must be treated as infrastructure, not features:

- **Differential harness vs `af.exe`** (built; open items = silicon arbitration
  and conflicted-key refeed) turns DECODE into a pipeline.
- **Self-hosted HIL instrument + nightly CI** (built prerequisite = the register
  bank; open items = firmware oracle + nightly sweep) turns SILICON into a
  pipeline. Firmware-reported oracles cover everything that does not electrically
  involve a pad; pad-electrical stays on the external probe.

The tiered-claims policy ([CLAIM_POLICY_LEDGER.md](CLAIM_POLICY_LEDGER.md)) keeps
this safe: decoded -> differentially validated -> statistically silicon-validated
-> individually qualified, with strict bitgen gated by tier and everything below
the configured tier failing closed.

### 4, 5, 6, 8, 14 — the subsystem/peripheral plane (plane 3)

This is "knowledge of all the peripherals." Priority order from
[PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md): analog (ADC/DAC/comparator) ->
MCU clock/PLL model -> DMA fabric handshake + peripheral-linked/descriptor modes
-> typed GPIO matrix -> advanced timers (GPTIMER0-4) -> UART external pins +
UART1-4 -> SPI/I2C silicon bring-up -> RTC/IWDG low-speed clock -> CAN/Ethernet
-> USB MMIO driver + host/OTG -> fabric AHB master + `EXT_INT0..7`. CAN
(transceiver), Ethernet (PHY), USB host (host), and RTC/IWDG (LSI/LSE clock) are
BENCH-gated and add no speculative driver until the hardware is present. The
fabric AHB master and DMA sidebands are entirely open routes; start read-only,
add canaries before any write.

### 7 — MCU External-AHB slave breadth

The complete-byte waited register bank, exact 32-bit reads, aligned
byte/halfword semantics, GPIO4.1 reset, and fail-closed non-SINGLE bursts are
qualified. A separate exact 16-bit held scratch now passes word write/hold/read,
SRAM-churn retention, repeated reads and GPIO reset. Open: integrating that
width with address isolation, subword access, upper-lane zeros and the public
ID/counter/W1C map; hard `MCU_RESETN`,
alternate/PLL3 bus clocks, and generic direct-D lowering. See
[MCU_FABRIC_ROADMAP.md](MCU_FABRIC_ROADMAP.md).

### 9 & 12 — BRAM and carry

BRAM is a bounded X13Y4 *read* proof plus 39 experimental config rows, of which
three now have behaviour -- `PORTA_OUTREG` at one Port-A read clock,
`PORTB_OUTREG` at one Port-B read clock in the bounded x2 dual-port oracle, and
`PACKEDMODE` with measured first-order effects in the write-path and dual-port
oracles (mechanism unclaimed) -- while `CLKMODE` remains a bounded null across
read, write-path and dual-port. The earlier write oracle did not land because
Yosys inserted redundant `emulate_read_first` input DFFs. With that transform
corrected, a source-built X13Y4 x2 OLD-mode pair writes `00` versus `11`
causally in 1,500/1,500 samples per variant. The rest of the behaviour matrix
(other writes, broader dual-port operation, byte enables,
width/mode, independent clocks, collision/read-during-write, high addresses,
other sites) is the labor, and it is exactly what the HIL instrument makes
cheap. Build the observable first: the older MCU-AHB read sweep is blind to
every B4 row. Carry needs arbitrary
seed/spill corridors and multi-chain placement beyond the one 33-site corridor.

### 10 & 13 — IO electrical/packages and timing

IO decode is much broader than IO *qualification*: the drive-current table and
pull/open-drain oracles are decoded, but dynamic OE/open-drain/bidirectional
electrical behaviour is human-gated, and only L48 is silicon-qualified. Q32
(the 16-node board package) first, then L100 and L64, each on its own package
board (BENCH). Timing is a conservative floor with a small exact overlay;
sign-off parity needs native wire/skew/IO/BRAM/hard-block/package/PVT models
before any Fmax-equivalence claim.

### 11, 15, 16, 17 — toolchain, cores, SDK, and boot

Scale is a P&R problem: the `agrv2k` Viaduct backend must close larger fresh
designs with a conduction-gated graph, constructive placement, and
congestion/timing awareness. SERV is a retained subset, not RV32I compliance.
SDK breadth is broadening the vendor primitive/parameter lowering and shipping
open MCU drivers with non-destructive evidence. Boot parity is a from-scratch
boot image on a blank/restored device plus option-pointer programming with a
staged recovery path — which itself depends on action 1 (a from-scratch image to
boot).

## Definition of done — full vendor parity + completely open

The project is "done" when all of the following hold and the parity ledger shows
every row at its top evidence tier with strict bitgen still fail-closed outside
proven behaviour:

- **Completely open (bitstream).** No `fabric_default.bin`: the base image is
  generated from the arch DB, `unknown_set_bits` is zero for any emitted image,
  a generated base boots on silicon, and the `NOTICE.md` canvas pin is removed.
- **Routing.** Every destination mux/input across the 22x13 grid has a decoded,
  admitted selector encoding; destination-mux coverage is 100%; any design the
  vendor flow can route builds through the open flow without fail-closing on a
  legal selector.
- **Logic.** LUT4/FF and all carry sites/modes qualified (largely done).
- **BRAM.** All sites, widths, modes, ports, output registers, byte enables,
  independent clocks, collision/read-during-write, and full address range
  qualified as *behaviour*.
- **Clock/PLL.** Arbitrary legal `(SYSCLK, HSE, source)` points, phase/duty,
  feedback/bypass, all outputs, and all oscillator sources, silicon- and
  timing-qualified; a bounded runtime clock-switch API exists.
- **IO/packages.** L48, Q32, L64, and L100 each silicon-qualified; dynamic
  OE/open-drain/bidirectional, drive-current, and pull electrical behaviour
  qualified; full pinouts emitted and checked.
- **MCU edge.** External-AHB slave full protocol with wide writable state, hard
  `MCU_RESETN`, and alternate clocks; fabric AHB master read+write; DMA
  sidebands; local + `EXT_INT` interrupt delivery.
- **Hard peripherals.** Every MMIO block has a typed open driver and
  non-destructive silicon evidence (with the transceiver/PHY/host/low-speed-clock
  hardware present for the gated blocks).
- **Timing.** Native wire/skew/IO/BRAM/hard-block/package/PVT model; Fmax
  sign-off equivalent to the vendor report.
- **Toolchain & cores.** The vendor primitive/parameter library lowers through
  the open flow; large fresh designs place and route; SERV reaches RV32I
  compliance or the retained subset is clearly scoped; the SDK ships open drivers
  for every hard block.
- **Boot/deploy.** A from-scratch boot image runs on a blank/restored device;
  option-pointer programming is qualified with staged recovery; the Pico UART and
  USB-CDC transports are end-to-end qualified.
- **Process.** Every claim carries an evidence tier; the differential and HIL
  pipelines run under append-only hash discipline; releases stay reproducible and
  fail-closed.

When the canvas is gone, routing coverage is 100%, every plane-3 subsystem is
driven and qualified, all four packages are on silicon, and the timing model
signs off — the AG32 is *completely* open and at vendor parity, bitstream and all.
