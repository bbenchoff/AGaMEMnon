# Supported feature matrix

This page defines AGaMEMnon's supported AGRV2K feature set. "Build supported"
means the public flow completes through strict bitgen. "Silicon-qualified"
means the emitted image was exercised by an electrically observable hardware
oracle. FCB configuration acceptance alone is not functional qualification.

The generated [FPGA parity ledger](FPGA_PARITY_LEDGER.md) tracks the same
boundary by encoding recovery, open-flow implementation, silicon state, and
package. It is currently a family-level inventory, not an exhaustive parameter
catalog.

[Vendor-parity status](VENDOR_PARITY.md) separately records what the completed
recovery campaigns did and did not promote. A closed workbench ledger is not
automatically a public build or silicon claim.

## Release flow

```text
synthesizable Verilog
  -> Yosys AGRV2K mapping
  -> nextpnr-generic --uarch agrv2k
  -> strict AGaMEMnon bitgen
  -> uncompressed SRAM image + compressed flash image
```

The release flow uses no vendor executable and no routed vendor checkpoint.
The Python generic-architecture adapter is available for small fixtures; the
`agrv2k` Viaduct backend is the supported scalable P&R path.

Baseline provenance: since 2026-08-14 emitted images are assembled onto a
**from-scratch design-neutral base** synthesized by `default_frame` from
promoted decoded DATA tables — no byte is copied from the vendor canvas at
build time. The base body is **100% byte-exact** (99,768/99,768) versus the
decoded canvas, a design built on either base is **bit-identical** (verified
across all 17 retained pack-regression artifacts plus the packaged
mcu-fpga-registers template), and the generated image **configures on
silicon** (`FCB_STAT = 0x000f0002`) while the canvas's own stale CRC is
rejected (`0x00000040`, `STAT_ERR_CRC`) — evidence in
`qualification/fabric_base_evidence.jsonl`. The complete 164-byte
global/configuration-chain preamble is regenerated from declarative fixed,
distribution, and parametric PLL profiles. `fabric_default.bin` (2.8 KB
compressed) is still shipped as a decode reference and differential anchor,
selectable via `AGAMEMNON_BASELINE`; it is not directly loadable (stale CRC),
and the *function* of the unnamed reserved bit-lines is still unproven. See
[the vendor-canvas anatomy](FABRIC_DEFAULT_CANVAS.md) for the byte-exact map of
what the file contains and what is decoded.

See [the provenance notice](../NOTICE.md) for the licensing and redistribution
boundary around the baseline, derived databases, external tools, and vendor
documentation.

## Fabric features

| Feature | State | Supported boundary |
|---|---|---|
| LUT4 and flip-flop RTL | Silicon-qualified | Combinational logic, registered feedback, counters, shifts, state machines, constants, physical-input registers, and large sequential designs |
| General routing | Silicon-qualified subset | Exact conflict-free physical selectors plus unanimous tile-relative selectors; predicted, conflicting, legacy, or unresolved selectors fail closed. Corpus counts are not device-coverage percentages; six new RMUX30 rows are experimental-only |
| Global clock | Silicon-qualified subset | Registered logic clocked from the single GCLK0 spine at the qualified seam selector, using the listed PLL configurations. One isolated distribution oracle (GCLK0 into X12Y3_ClkMUX02) plus the tiles exercised incidentally by other qualified designs; per-tile clock arrival elsewhere is unmeasured, and the former "near and far tiles" phrasing is withdrawn as unfalsifiable |
| Physical outputs | Silicon-qualified L48 subset | Characterized header outputs, left-edge PIN_25 through PIN_28, and **all ten TOP-edge decimal physical leads PIN_10 through PIN_19**, built by the ordinary CLI with `--pcf`. The closing PIN_10/PIN_11 singles and same-tile pair toggle only their intended GP4/GP1 leads under both Pico pulls, with zero selector debt; the production pair is byte-identical to the measured candidate and its retained route repacks byte-identically. These names are decimal L48 package-lead labels, not hexadecimal indices. The left-edge four also reproduce from the ordinary CLI as of 2026-08-15 (`agamemnon build qualification/left_edge_outputs.v --pcf qualification/left_edge_outputs_L48.pcf --research-unsafe`, image sha256 `a63ab5bc26bb4852555fb93863f065ba020564ec77e801cd4d67d4bcf865aba3`, 35 pips / 0 unmapped / 0 predicted / 0 legacy-abs, Pico GP12 404,383 Hz, GP13 405,612 Hz, GP16 405,168 Hz, GP17 411,144 Hz with GP8 (PIN_18, undriven) 0 Hz as the negative control, FCB 0x000f0002). Flow caveat: the Python-architecture PCF placer composes experimental options, so these pad builds need `--research-unsafe`; release-strict rejects them |
| Physical inputs | Silicon-qualified L48 subset | PIN_10, PIN_11, PIN_15, and PIN_19; PIN_19 also has a qualified registered path. PIN_25 through PIN_28 are qualified through their exact left-edge InputMUX→RMUX→IMUX corridors as single-consumer direct inversions observed at PIN_18. Each returned the repeated `0→1, 1→0` truth table. The PIN_25 controlled image pair also board-proves `RMUX68@9,4→RMUX74@11,4`, removing that historical negative; this does not qualify arbitrary fanout or the complete four-link bidirectional node |
| Bidirectional node pinout | Build-supported, hardware-unqualified | One strict L48 image composes PIN_25 through PIN_28 local data-low tie-offs, four independently owned dynamic-OE trunks, four exact input corridors, PIN_19/PIN_16 UART, PIN_15 phase clock, and hard HSE. All 102 routed PIPs are mapped with zero legacy, predicted, or unmapped selectors; electrical drive/release/readback remains human-gated |
| MCU GPIO bridge | Silicon-qualified subset | Four-bit MCU-to-fabric-to-MCU inverter loopback over all input combinations. Exact L48 GPIO5 data/OE lanes 0 and 1 plus input lane 2 are also qualified through pure-open images; the boundary emits coherent inactive `BBMUXS` terminal defaults. No full GPIO-matrix or package-pin claim |
| External AHB read | Silicon-qualified | All 32 fabric-to-MCU data lanes in one simultaneous read |
| External AHB write | Silicon-qualified subset | All 32 MCU write-data lanes in protocol-valid four-bit groups |
| External AHB request controls | Silicon-qualified subset | Registered isolation of `HADDR[4:2]` through `MCU_DIN76:78`; all eight values observed during a 256-address SRAM sweep. Separate pure-open oracles qualify HADDR[5], HADDR[3], and simultaneous HADDR[1:0] logic ingress on the complete-byte waited bank; HADDR11 also reaches the x9 AddressA12 route at logical word addresses 0/512. On the exact 16-bit held checkpoint, HADDR[3:2] gates writes so +4/+8/+c cannot alter +0 and gates low-16 aligned word reads so +0/+4/+8/+c return `[state,0,0,0]`; HADDR[1:0] and HSIZE[1:0] compose into independent byte tokens, aligned halfword/word write selection, and CPU-visible aligned unsigned subword lane selection. Misaligned transfers remain outside scope |
| External AHB bus clock | Silicon-qualified subset | Pure-open default `bus_clk = sys_gck` delivery qualifies direct-D sites X14Y11 slice4 through slice7, an eight-state three-bit counter, and a 16-bit LFSR with 500 distinct reads. Across three runs and 45 intervals the LFSR advances exactly one step per undivided MTIME tick — a 1:1 ratio, which is the qualified quantity; the absolute rate previously printed as 10 MHz assumed a 10 MHz HSI/MTIME and is an [open question](MCU_CLOCKS.md#external-ahb-bus-clock) now that MTIME has been measured at 14.08 MHz. A GPIO4.1-fed synchronous reset held all 16 state bits at zero and re-armed in three runs. Hard `MCU_RESETN`, PLL3 BUSCLK, unrestricted direct-D lowering, and the fourth binary carry cone remain unqualified |
| External AHB constant slave | Silicon-qualified | Constant-ready, OKAY-only combinational endpoint; 32-bit reads return `0x4147414d`, writes complete without effect; no wait/error/register-bank claim |
| External AHB register classes | Silicon-qualified exact L48 subset | The default SDK profile composes canonical ID32 `0x4147414d` at +0, zero-extended scratch16 at +4, counter3 at +8, and W1C1 at +c. Three sequential full-map SRAM-only runs pass exact LW values, every ID byte/halfword lane, unsigned-load zero extension, scratch word/halfword and independent byte +4/+5 semantics, foreign-address isolation, retention, coexistence, GPIO4.1 reset, all eight counter states, and the qualification-only W1C set/clear/set-priority matrix. A separately selectable exact GPIO5-W1C derivative removes the bit1 self-test set hook and uses MCU GPIO5 DATA0/OUT_EN0 as an independently routed sustained-level source. One base negative (`status_errors=162`), one OR control (`2`), and three production runs (`0`) preserve every non-status check and prove low/hold/clear, high/set-priority, and reset dominance. GPIO5 is software-controlled qualification stimulus, not a package-pin input or autonomous asynchronous event. The deterministic composers, structural replays, raw/compressed images, and causal controls are hash-pinned and strict-clean. The public16 and older complete-byte profiles remain separately available. An application-owned autonomous status source, misaligned and signed loads, higher/full-window decode, bursts, arbitrary placement/width, other packages, and a generic register-bank generator remain open; deterministic MCU exception behavior from HRESP is retired on L48 |
| Fabric local interrupts | Silicon-qualified routing/cause and integrated command subset | Four distinct sources route simultaneously to `local_int[3:0]`; lanes independently deliver local causes 16–19 with the matching `mip` bit. One strict AHB image uses HWDATA[3:2] to select a one-hot cause and HWDATA[1:0] for mask/ack/set commands. An SRAM-only MCU run counted three exact deliveries per cause, acknowledged each, re-armed twice, held events while masked, and cleared on GPIO reset. On the attached board, post-reset/pre-SRAM-config local `mip` was zero with local `mie` both clear and armed; configured held-reset/released state was also zero. Under the default bus clock, 64 set and 64 acknowledge operations each completed in exactly 21 MTIME ticks and synchronous reset clear took 40 ticks (tick counts; the absolute bus-clock rate is an [open question](MCU_CLOCKS.md#external-ahb-bus-clock)). The state is deliberately shared across the selected lane rather than four simultaneously retained pending bits. Reads return zero; POR, PLL3/alternate clocks, hard `MCU_RESETN`, state readback, and active-pending pre-`mie` visibility remain open |
| Dedicated carry | Silicon-qualified opt-in | Same-tile short chains and one 33-site corridor containing a seed plus up to 32 arithmetic stages |
| BRAM | Silicon-qualified subset | One x18 Port-A path, one x2 Port-B read/control path, all nine X13Y4 read-only x9 data bits through exact per-lane projections, a simultaneous strict-open x9 bundle, and the exact 1024-aligned-word HADDR[11:2] address bundle. Separately, 39 configuration rows across X13Y1..Y4 are admitted only under `experimental-strict`; the admissions themselves are config-encoding, not behavioral claims. `PORTA_OUTREG` adds exactly one Port-A read clock in the exercised read mode; `PORTB_OUTREG` adds exactly one Port-B read clock in the bounded X13Y4 x2 single-clock dual-port composition. `PACKEDMODE` has a measured first-order effect in bounded write-path and dual-port oracles, with no mechanism claimed; `CLKMODE` remains a bounded null across the three tested compositions. Note the two surfaces: the CONFIG surface covers X13Y1 through X13Y4, while PLACEMENT is X13Y4 ONLY |
| ADC/fabric routes | Build-supported, hardware-unqualified | Distinct read-only ADC0 result bits 0/1 and EOC typed corridors; no ADC configuration or electrical claim |
| Fabric-analog blocks over External AHB | Silicon-qualified driver/register subset; the IP macro itself is not open-emitted | ADC0, ADC1, ADC2 (12-bit one-shot), DAC0, DAC1 (10-bit), CMP0 **unit 1**, and the internal DAC0→ADC-channel-4 / DAC1→ADC-channel-5 loopback taps are qualified on the L48 part through the `0x60000000` window. Evidence: a DAC0 sweep {0,128,…,1023} read back, on one representative run, 0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095 on ADC0 channel 4. The qualified claims are the run-invariant ones — monotonic, ~4.00× linear (12-bit result over 10-bit code), saturating at full scale — reproduced on ADC1/ADC2 and via DAC1→channel 5 (on ADC0). The exact codes are NOT a constant: an independent run of the same sweep gave 0, 511, 1024, 1538, 2054, 2573, 3085, 3594, 4095, so nothing should assert them; CMP0 unit 1 flipped at DAC0 codes 94/188/281/373 for the VREF/4, VREF/2, 3·VREF/4, VREF taps against 93/186/279/372 predicted from the vendor RTL. The MCU side is fully open (SDK drivers, SRAM staging, FCB configuration, External-AHB reads); the fabric image instantiates the **vendor `analog_ip` hard-macro wrapper**, which AGaMEMnon's own bitgen does not emit, so this is not a claim that the open flow can synthesize the analog IP. **Honest negatives:** CMP0 **unit 2** is register-readable and its enable takes, but its output read high at every DAC0 code under **both** PSEL2 selects, so its positive-input mux differs from unit 1's in an undocumented way — UNPROVEN, not working. External ADC channels 0–3 read full scale (`0xfff`), which means only that **no usable analog input was presented**; the cause is **not established**. An earlier note attributing it to unbonded L48 analog pads is **withdrawn** — the datasheet-derived pin table places `ADC_IN0..IN3` on PIN_10..PIN_13, and those four pads are bonded and harness-confirmed working as ordinary digital IO (they are the same pads UART0 TX, I2C0 SDA, and SPI0 SCK/CSN were qualified on). Unconfirmed candidate causes: the analog input mux is not enabled for those channels; the pad is held in digital mode by the fabric IO ring and never switched to its analog function; the input is unconnected on this board; or a reference/bias is unconfigured. Treat channels 0–3 as UNPROVEN, not known-absent. CMP hysteresis/mode bits, ADC/DAC DMA and continuous-scan modes, and multi-entry sequences remain unexercised |
| PLL | Byte-exact emitted subset; silicon-qualified subset | Emission is fail-closed to 45 `(SYSCLK,HSE)` pairs: the seven byte-exact vendor-oracle profiles `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, `(100,16)`, `(60,8)`, `(100,12)` plus 38 further HSE=8 `SYSCLK` rates qualified on silicon. The silicon-frequency-qualified surface is HSE=8, `SYSCLK` **4-248 MHz** — 43 rows in `qualification/pll_freq_evidence.jsonl`, each locked, selected, and measured against the host wall-clock, worst 0.058% off the requested rate; the DAP/SWD link survives the halt/readback at every rate up to 248 MHz. `(100,16)` and `(100,12)` cannot be exercised on the 8 MHz-HSE reference board (they require 16/12 MHz HSE), so they remain preamble/timing-qualified only. No phase, duty-cycle, feedback, bypass, other-output, or non-8 MHz-HSE claim. |
| Timing | Conservative estimate with bounded exact overlay | 542 certified local pairs cover 9,375 ordinary L48 route pips; 226,540 ordinary route pips retain worst-family fallback. Requested failure is fatal, but this is not a complete Fmax/sign-off model |

## Current integration boundary

The 16-node board work is gated by seven ordered integration items. Their
current evidence boundary is:

1. Default External-AHB `bus_clk = sys_gck` delivery is timer-qualified at
   exactly one bus clock per undivided MTIME tick. The absolute rate was
   inferred as 10 MHz from the vendor-nominal HSI; MTIME later measured
   14.08 MHz, so that figure is an
   [open question](MCU_CLOCKS.md#external-ahb-bus-clock). Direct-D feedback is
   qualified at X14Y11 slices 4 through 7, an explicit three-bit counter
   produces all eight states, and a 16-bit LFSR produces 500 distinct reads.
   GPIO4.1-fed synchronous reset-to-zero and re-arm are also qualified; hard
   `MCU_RESETN`, equal post-release phase, and unrestricted direct-D lowering
   remain open. HADDR[3:5], a paired HWRITE/HTRANS1 qualifier, and exact
   HWDATA[0], HWDATA[1], HWDATA[2], HWDATA[3], HWDATA[4], HWDATA[5], HWDATA[6], and HWDATA[7]
   registered consumer
   footprints are represented. A pure-open byte-wide posted-storage oracle now passes all
   256 values, immediate write/read, back-to-back newest-write forwarding,
   and repeated writes through exact one-consumer lane footprints. A
   registered HADDR[2] tag distinguishes writable offset 0 from an ignored/
   zero offset 4 without cross-address forwarding. One combined pure-open image
   now integrates immutable ID low byte `0x4d`, the byte-wide scratch, a
   read-only three-bit dedicated-carry counter, and one-bit W1C status at
   offsets 0/4/8/C. It passes all 256 scratch values, ignored ID/counter writes,
   constant nonzero counter cadence plus phase-swept eight-state coverage, the
   complete set/hold/zero-write/clear/re-arm/set-priority status sequence, and
   cross-register preservation. A second pure-open image integrates GPIO4.1
   synchronous reset: 72 asserted-reset state reads are zero across initial
   hold and reassertion, writes are blocked, two releases re-arm the counter,
   scratch, and status, and a final reassertion clears them. A separate
   immutable-ID endpoint qualifies one controlled wait per single aligned
   word read or ignored write, with exact `0x4d` data and OKAY response. The
   first writable-bank composition retained deterministic wait timing but
   corrupted lane6, and a separate-capture retry reconfirmed the already
   known MCU-only capture-Q boundary. An exact lane6-only commit-stage-F retry
   also retained the same bit-6 corruption, exculpating combinational commit
   phase alone. Holding HREADYOUT low through the registered commit cycle also
   reproduced the original failure unchanged, exculpating response-release
   duration. Restoring own-Q to its pure-open-qualified I3 pin also reproduced
   it, exculpating feedback-pin placement. All remain retained coupled
   negatives, not dead-PIP claims. An independent raw-Q witness on HRDATA8
   matched ordinary HRDATA6 in all 256 cases; both showed the same sticky-high
   127-error pattern, localizing the failure to stored lane6 state rather than
   its class-mux read branch. Moving state out of slice15 into a separate
   reset-aware register reproduced the same signature, exculpating the Q
   primitive and replacement storage site; the changed HWDATA6 ingress route
   versus the qualified pure-open bank was causal. Restoring that route alone
   made basic `0xa5`/`0x3c` exact but retained a one-transfer lane6 lag. The
   final complete-byte composition advances only lane6 commit from the scratch
   commit-stage F: all 256 values and 128 back-to-back pairs pass with OR/AND
   `0xff`/`0x00`, ID/W1C/counter/reset remain correct, and the waited loop adds
   2587 cycles over SRAM. Hard MCU_RESETN, upper-zero completion on the
   complete-byte route, bursts, and byte/halfword semantics remain open. A
   strict follow-on preserves that route, relocates HRDATA7 onto its qualified
   RMUX56 exit, and drives HRDATA8 explicitly zero. All 256 halfword, 256 word,
   and 128 mixed low-nine-bit checks pass while the complete-byte regression
   remains green. The free RMUX13 GND branch also qualifies HRDATA9 zero across
   the same transfer classes, and the one-hop RMUX72 branch similarly qualifies
   HRDATA10, while the free RMUX48 branch qualifies HRDATA11. A new
   constant-zero LUT qualifies HRDATA12 after a local scratch6 consumer
   relocation, the free RMUX20 branch qualifies HRDATA13, the X19Y9 RMUX15
   branch qualifies HRDATA14, and a route-only branch from X20Y9 RMUX69
   qualifies HRDATA15. A direct RMUX20 fanout qualifies HRDATA16, and a
   route-only RMUX08 branch qualifies HRDATA17. A grouped route-only image
   qualifies HRDATA18,19,21–26,28–31; alternate exact-ingress fanouts close
   HRDATA20/27 and exact 32-bit scratch reads. A resettable sticky witness also
   qualifies simultaneous HADDR0 logic ingress. A follow-on composes HADDR1
   and qualifies aligned byte/halfword semantics across all four classes. The
   public core also rejects every non-SINGLE HBURST encoding with HRESP and no
   state mutation; acceptance of bursts is RETIRED because the recovered
   HBURST0/1 exits conflict with qualified readback and the attached MCU has
   no autonomous non-SINGLE source under the campaign rails. This is an
   offline fail-closed boundary, not a silicon burst or exception claim. The
   HRESP-to-MCU-access-fault claim is RETIRED on the attached
   L48: an exact two-cycle response used the qualified HREADYOUT OMUX20 route,
   added 511 MTIME ticks across 256 reads and 297 ticks across 256 fenced
   stores, and exposed the `0xffffff4f` active-response witness, but raised
   zero load or store access traps after a passing `ecall` trap-path control.
   The response also spilled into the following ID check. This is retained
   architectural negative evidence, not a dead-PIP claim; public support makes
   no claim that fabric HRESP becomes an MCU exception. HWDATA0 is
   additionally live directly at lane-zero storage, and all X14Y11 slice5
   HWDATA5 terminals are live. The slice5 DD88 storage/feedback footprint also
   follows HWDATA5 exactly with commit tied high, while routed commit/local
   qualifier variants retain exact lower lanes but lane5 constant one. The
   qualified replacement captures HWDATA5 at slice5, applies commit/hold in a
   separate next-state LUT, and stores that single input at slice8. Two exact
   route-through leaves distribute commit constructively without broadening
   their four-site footprint family. Lane6 uses the exact X14Y12 slice15
   HWDATA6 I0 consumer as a folded BB88 commit/hold store; HREADYOUT remains
   constant high through a separate strict X15Y12 slice12 source. The tested
   lane7 storage uses the exact X14Y11 slice0/I1 HWDATA7 terminal, live commit
   at I2, and own-Q hold at I0. The X14Y12 slice15 combinational
   identity reuse and X14Y11 slice8 relative direct-D candidate remain unqualified.
2. Four distinct fabric sources route simultaneously to `local_int[3:0]` and
   independently deliver local causes 16 through 19 with matching `mip` bits.
   A single strict AHB image selects the one-hot cause with HWDATA[3:2] and
   applies 00=mask-off/hold, 01=mask-on/ack, 10=mask-off/set, or
   11=mask-on/set in HWDATA[1:0] at offset 4. One SRAM-only MCU run counted
   three exact traps per cause, observed `mcause=0x80000010` through
   `0x80000013` with one-hot trap-time `mip`, acknowledged every delivery,
   re-armed twice, held the first and third events behind the fabric mask,
   and cleared on GPIO4.1 reset. This is a sequential one-hot command bank
   with one shared pending/mask state, not four simultaneous pending stores.
   A second oracle observed zero local `mip` after ordinary board reset before
   the SRAM FCB load, both with local `mie` clear and armed, and zero while
   configured reset was held and after release. At the separately qualified
   default `MCU_BUS_CLOCK`, 64 set and 64 acknowledge transitions each
   took exactly 21 MTIME ticks; synchronous GPIO reset clear took 40 ticks.
   This is not POR, blank-fabric, flash-content, PLL3/alternate-clock, hard
   `MCU_RESETN`, or asynchronous-reset qualification. Reads intentionally
   return zero; state readback and active-pending pre-`mie` visibility remain
   outside the claim. The absolute `MCU_BUS_CLOCK` rate quoted above is an
   [open question](MCU_CLOCKS.md#external-ahb-bus-clock); the tick counts are
   not.
3. Fabric-driven output enable and open-drain behavior are not electrically
   qualified. Static input/output support must not be read as bidirectional
   shared-wire support; the prepared one-pad and four-link images remain
   human wiring gates.
4. The complete L48 node pinout is closed offline and HUMAN-GATED electrically.
   Its strict image composes four distinct left-edge OE owners, four exact
   input paths, local data-low tie-offs, control UART, TDMA phase clock, and
   hard HSE. Bitgen maps 102/102 data PIPs with no legacy, predicted, or
   unmapped selectors; a 64-case UART truth audit and 16-state phase/enable
   audit pass. No drive/release/readback or package-electrical claim follows.
5. The register-window soft-UART core and fail-closed protocol boundary pass
   offline loopback regression; its L48 route, silicon behavior, and physical
   TX/RX binding remain unqualified, as do hard-UART TX/RX fabric routes.
6. Q32 has recovered legality and bond data but no silicon qualification.
7. The Pico mask-ROM programmer is software-tested; target-side wiring and
   interrupted-operation recovery remain human/bench gates.

The x9 BRAM fault was independent of those seven ordered gates. Its exact
21-hop ingress built and read actively, but sparse readback-buffer emission
made the early comparison appear address-static. Three explicit-BRAM,
one-terminal parity oracles then tested
AddressA[3]/IMUX09, AddressA[4]/IMUX08, and AddressA[5]/IMUX07 independently
with all inactive terminals coherently tied; each returned `0xfffffffe` for
256/256 reads. The named terminal identity/permutation class is therefore
functionally eliminated. A subsequent transplant of the only two known
non-preamble raw tail bits also remained static for 256/256 reads, eliminating
that reserved group as a sufficient cause. The qualified `pll-100-8` preamble
was also negative alone, and an all-known-groups interaction candidate remained
static. A bidirectional ownership comparison then found that the sparse open
identity-LUT overlays were wrong at the two exact x9 readback route-through
sites. Emitting their complete footprints changed lanes 0/1 from low to high
(`0xfffffff8` to `0xfffffffb`), proving high-state visibility through those
exact sites. A third vendor-shaped slice footprint did not expose lane 2.
Finally, all-zero and all-one images differing at every one of the 9,216
`INIT_VAL` cells produced the same `0xfffffffb` at all 256 addresses. The
subsequent complete-terminal audit found that the reduced open route leaves
AddressA[6:12] without drivers or terminal selections, while the working
vendor route drives all seven from HADDR[5:11]. Completing those routes was
still static. A reverse whole-image descent then isolated X22Y4
`CFG_IOMUX11[9]` as necessary: clearing that bit alone makes the working clone
static. Adding it to the then-sparse pure-open x9 image yielded two values,
proving it necessary but exposing only two readback lanes. Clone descent then
showed that the apparent second break was a projection-width loss at the two
readback route-through tiles, not a dead BRAM. Six missing named footprint
bits complete those exact buffers. With automatic x9 HSE emission and those
footprints, the ordinary pure-open oracle returns all eight low-three-bit
identity values. Three independently initialized pure-open images project
word-address bits `[2:0]`, `[5:3]`, and `[8:6]`; together they reconstruct all
256 exercised addresses exactly. A separate pure-open route exposes logical
data bit3 and matches aligned word-address bit3 for 256/256 reads. An INIT
projection onto that lane also alternates correctly between logical word
addresses 0 and 512 for 64/64 samples, qualifying the exact
HADDR11-to-AddressA12 corridor and X14Y7 slice3 route-through footprint.
Direct pure-open follow-up also qualifies logical data bits4 and 5. Bit4 uses
`BufMUX12 -> RMUX92 -> RMUX85 -> RMUX49 -> BBMUXE06`; bit5 exposed a wrong
open graph assignment and is fixed by the silicon-qualified
`BufMUX13 -> RMUX92 -> RMUX75 -> RMUX20 -> BBMUXE07` corridor. Both lanes
match aligned word-address bit3 for 256/256 reads, and the natural corrected
q5 build is byte-identical to its observed open-bitgen image. The qualified x9
data surface is therefore all nine logical lanes within these exact
projections. Full-width INIT permutations also make logical data bits6, 7,
and 8 match aligned word-address bits0, 1, and 2 respectively for 256/256
reads through their exact direct corridors. The characterized x9 wrapper maps
these lanes to physical DataOutA15, DataOutA16, and DataOutA7. Logical q4 and
q5 are also qualified simultaneously through an exact paired route. Its q4
path uses `BufMUX12 -> RMUX75` and the source-dependent
`RMUX43 -> BBMUXE06` selector `{1,6}`; the earlier source-only fallback
`{0,6}` was the defect. An atomic qualified-corridor reservation then routes
all nine outputs simultaneously. The strict-open payoff returns all 256
identity words over HADDR[9:2]; bits0..7 each match 256/256, while q8 is zero
over this bounded address range and retains its independent two-state proof.
The remaining high-address range, broader writes,
other modes/sites, and collisions remain fail-closed, and output-register
selection is reachable only through the experimental config gate.

The GPIO5 boundary fault is closed for two exact L48 source pairs. The original
lane-1 route and an independent lane-0 differential route both failed when
the seven otherwise inactive X9Y5 `BBMUXS` fields were left zero. Setting
terminal 8 on `BBMUXS0/1/3/4/5/6/7` while preserving the active `BBMUXS2`
return path restores both lanes. Fresh pure-open lane-1 and lane-0 images are
byte-identical to the silicon-positive coupled candidates and each returned
`[0,0,1,0]`. The claim is limited to data/OE lanes 0 and 1 with input lane 2;
all other GPIO5 lanes, simultaneous breadth, direction modes, and package-pad
bindings remain fail-closed.

## Routing policy

The release selector database contains 659,759 conflict-free physical edge
encodings and 62,044 tile-relative encodings whose physical observations all
agree. Conflicting relative keys are omitted. Architecture generation and
bitgen enforce the same selector boundary.

The 659,759 rows are 90% of 733,862 keys in the historical **observed
recovery corpus**. They are not “99% of the fabric” and do not imply that 90%
of all device routes are available. The measured baseline exposes at least
one clean edge in 159 of 322 grid tiles. The later R2 campaign witnessed all
71,697 live rows in its separate frozen target denominator, but current public
main promotes only six reviewed RMUX30 rows from that program, all disabled by
default behind `experimental-strict`.

The device database also carries a small negative-evidence set of routing edges
that the release router conservatively blocks. These were originally classified
from negative silicon trials, but that classification is now known to be
unreliable: the trials were not truly isolated. They came from one large,
congested MCU-exit design, and the failures were a congestion-context effect
mis-attributed to individual edges. On silicon, **six** of the originally
catalogued fourteen edges -- `RMUX21@(14,10)->RMUX87@(14,8)`,
`RMUX63@(10,4)->RMUX68@(9,4)`, `RMUX87@(14,8)->RMUX68@(14,7)`,
`RMUX08@(12,4)->RMUX32@(14,4)`, `RMUX74@(11,4)->RMUX08@(12,4)`, and
`RMUX68@(9,4)->RMUX74@(11,4)` -- conduct in
clean, isolated builds, so they have been removed from the negative set and are
admitted as silicon-verified conducting edges. The remaining **eight** stay
conservatively blocked and are treated as unverified, not as proven-dead. Two
2026-08-14 campaigns bound what is left. Forcing a chosen crossing requires
banning all 4,113-12,489 other enumerated crossings of a geometric cut; when the
readback is the MCU-dout path, which must re-cross that same cut, the resulting
images do not work at all -- **matched sibling controls keeping a different
non-catalogued crossing also read STUCK** -- so only *positive* readings mean
anything. Moving the readback to a **physical pad on the destination side**
removes that confound (the observation channel never crosses the cut) and closed
the last two edges positively. The gate mechanism -- negative evidence has absolute precedence over
positive attribution -- is unchanged; only the data was corrected. See the reframe narrative in
[AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md) and the live log in
[CONDUCTION_REFRAME_STATUS.md](CONDUCTION_REFRAME_STATUS.md).

An explicit `--research-unsafe` build profile separately exposes normalized
vendor-derived, conflicted-majority, decoded-template, and predicted selector
sources. The public conflict atlas preserves 74,103 conflicted physical keys
and their full observed pair/count distributions. Such images are always
non-release and carry a hash-bound provenance sidecar; this does not promote
the R2 occupancy witnesses, qualify a package or behavior, or weaken the
release selector gate. The conservatively blocked negative-evidence edges remain blocked in release images.

Simultaneous MCU bundles use global source matching and bounded corridor
negotiation rather than greedy per-lane reservation. Recovered vendor paths
that cross `alta_slice` remain logical-cell evidence and are not admitted as
transparent routing PIPs. The L48 constant-slave qualification covers the
corrected 32-lane result and both response controls.

## Dedicated carry

`build --uarch --hard-carry` lowers eligible arithmetic to `AG32_FA`, adds one
physical seed per independent chain, places the chain contiguously, and uses
normal LUT-to-FF capture.

Multiple same-tile chains are accepted when:

```text
sum(arithmetic stages) + number of chains <= 9
```

One chain may instead use the qualified 33-site order through X20Y11,
X20Y12, and X20Y10. Other spill locations, multiple long chains, branches,
and malformed chains fail closed. Dedicated carry is opt-in.

## BRAM

The integrated BRAM model exposes independent A/B clocks, enables, addresses,
data, widths, and write controls. Yosys can infer an `ALTA_BRAM9K` for the
memory pattern used by the SERV example.

Hardware qualification includes one characterized x18 Port-A path, one exact
x2 Port-B read/control corridor, and the X13Y4 x9 read-only subset described
below. During recovery, bounded clock/reset-field and coupled local-control
negatives were joined by three explicit-BRAM parity negatives:
AddressA[3:5] at IMUX09/08/07 each remained static for 256 reads with the other
terminals tied coherently. Those records eliminate the named terminal
identity/permutation class, not x9 generally. All results are retained in
`qualification/bram_evidence.jsonl`. The two reserved per-wordline-tail bits
outside the physical feature map were also transplanted together and remained
static; they stay unnamed. The 22-byte generated `pll-100-8` preamble shared by
the qualified open x18 image and working vendor x9 image was likewise negative.
Finally, combining that preamble and tail residue with the complete coherent
vendor local surface still returned `0xfffffff8` for 256 reads. Correcting the
two exact identity route-through footprints then exposed constant highs on
lanes 0/1, but an all-zero/all-one `INIT_VAL` discriminator remained identical
at `0xfffffffb`. The earlier static negatives remain valid, while their constant
values now describe readback visibility/default state rather than initialized
array data. Whole-image clone descent subsequently proved the HSE input-enable
field necessary for the then-sparse image. Descending the remaining owned
groups showed that the supposed default-field break was only loss of observed
readback width. Six exact masked IMUX/RMUX footprint bits at X14Y4 slice5 and
X14Y8 slice8 restore all three lanes; pure-open emission now automatically
includes the x9 HSE field and regenerates the silicon-tested images. Three INIT
projections return the expected word-address triplets for 256/256 reads each.
Upper-lane follow-up then proved the X14Y4 slice0-to-HRDATA3 output half,
all-zero/all-one INIT sensitivity, and logical lane3 identity with a
three-pattern binary signature. A four-HADDR-bit pure-open oracle matches data
bit3 for 256/256 reads. Finally, a word-address-bit9 INIT projection
distinguishes word addresses 0 and 512 for 64/64 alternating samples,
qualifying HADDR11/AddressA12 through X14Y7 slice3. Earlier static observations
remain valid, but their interpretation as dead INIT/address behavior is
superseded; the isolated q3 constant was specifically caused by incoherent
constant address terminals. Direct pure-open oracles subsequently qualify
logical data bits4 and 5 for 256/256 reads. The q5 failure was a mislabeled
egress corridor in the open graph, corrected to the exact
BufMUX13/RMUX92/RMUX75/RMUX20/BBMUXE07 path; it was not an INIT-load or
terminal-identity defect. A later simultaneous q4/q5 oracle isolated and
corrected the source-dependent q4 BBMUXE6 selector; both lanes then matched
their complementary functions for 256/256 reads. The allocator now reserves
that exact corridor only when q4/q5 are simultaneous, and the resulting
nine-output strict-open image returns identity words 0..255 exactly once.
Other BRAM tiles, the remaining
high-address lanes/range, arbitrary fresh corridors, other widths/modes,
broader writes, and read/write collision semantics remain
unsupported.

The B4 configuration campaign separately admitted 39 L48 parameter-encoding
rows for BramTILE X13Y1 through X13Y4. Those rows are
`differentially_validated`, permitted only under `experimental-strict`, and
denied under the default `release-strict` policy. The admissions do not
establish the behavior of writes, mixed widths/modes, independent clocks, or
collision semantics. Two surfaces must be kept apart when reading that scope:
the CONFIG surface (`agamemnon/engine/pips_bram_pll.csv`) covers BRAM tiles
X13Y1 through X13Y4, while the PLACEMENT surface
(`agamemnon/chipdb/bram9k_bel.csv`, `agamemnon/chipdb/bram_cell.csv`) is
X13Y4 ONLY, so exactly one BRAM site can be placed and read.

One of those rows now has measured behaviour, and one pair has a measured
bound. `PORTA_OUTREG` adds exactly **one** BRAM clock of latency. The
observable is a fabric-side cycle-sensitive oracle — 500 samples x 3 runs,
parity of `hrdata[2:0]`, SRAM-only, `FCB_STAT 0x000f0002` — which read
base = `{0x8,0xb,0xd,0xe}` EVEN and an extra-pipeline-register positive
control = `{0x9,0xa,0xc,0xf}` ODD; `PORTA_OUTREG` measured ODD, matching the
control. `PACKEDMODE` and `CLKMODE` measured EVEN in that read-only
mode (x18 Port-A read, identity ROM contents, 4-bit fabric address, Port-B
unused, single clock domain). `PACKEDMODE` returned a bounded null in that read-only oracle, but as of 2026-08-15 it has **measured first-order behaviour** in both write-path and dual-port oracles: one config byte (66,222) moves the former from `{0,5,A,F}` to `{0,4,8,C}` and collapses the latter from 7 distinct values to 2. **No mechanism is claimed.** `CLKMODE` remains a **bounded null** across all three compositions, not a characterization. `PORTB_OUTREG` adds exactly one Port-B read clock in the retained X13Y4 x2 single-clock dual-port oracle: the one-bit variant changed `{0,2,4,6,8,A,C}` to `{2,4,8,E}` in three 500-sample runs, exactly matching the one-clock cycle model. One exact X13Y4 x2 OLD-mode write composition is silicon-qualified. Its source-built pair has identical full all-one physical INIT, route, control, schedule, clocks and output and differs only in its two DataInA LUTs: write-`00` read `0xfffffff0`, write-`11` read `0xfffffff3`, in three 500-sample runs per image, FCB accepted with zero mapping debt. The older no-write result was a synthesis-topology failure caused by current Yosys `emulate_read_first` DFFs on the hard-BRAM write inputs. The production Qin pass now bypasses only structurally named, same-clock emulation DFFs for uniform physical initializers; mixed/patterned designs keep their prior topology and NEW/NO_CHANGE remain behaviour-unqualified packing choices. This qualifies that exact composition only. Uniform all-zero/all-one narrow initialization is deterministic; patterned narrow initialization and broader write semantics remain unqualified. Still
open: broader BRAM writes, broader dual-port operation, the remaining config modes, and most
B4 rows. The existing MCU-AHB read sweep is **blind** to all B4 BRAM rows:
one read transaction holds the address stable far longer than any pipeline
stage the config selects, so an output register, a packing change, and a
clock-mode change are all invisible to it. Evidence:
`qualification/bram_evidence.jsonl`.

## Timing and PLL

`build --freq MHz` selects the emitted fabric PLL, requests timing closure at
that same frequency, and fails if nextpnr misses the target. Cell timing covers
conservative LUT, flip-flop setup/hold/clock-to-Q, and carry arcs. Wire timing
uses a hash-pinned exact table for 542 certified local OMUX-to-IMUX resource
pairs and the largest decoded delay for each driving mux family everywhere
else. Those pairs cover 9,375 of the 235,915 ordinary routing pips in the
strict L48 release graph; the other 226,540 retain the conservative family
fallback. The exact 0.401 ns charge is the decoded slow-corner maximum for the
whole annotated `alta_slice -> OMUX -> IMUX` local pattern. The slice cell arc
is still charged separately, adding conservatism. Dedicated feedback and other
non-`ROUTE` pips retain their existing models. Non-L48 package selections keep
the conservative model for every routing edge. When no frequency is supplied
by the CLI, project, or environment, the qualified default is 10 MHz.

The timing report is not a complete silicon Fmax model. The four-node local
pattern is not split because its 0.613 ns total has no proven per-pip
decomposition. Hard-block/BAR endpoints without an unambiguous public-pip
mapping also remain conservative. Exact native wire-class binding, clock skew,
IO, BRAM, PLL, package, and broad PVT delays are not modeled.

PLL emission is one closed-form equation, not a per-ratio table. The vendor
divider math (`check_pll`) plus a preamble bit-map that was differentially
validated byte-exact on every point of a 53-point vendor `(SYSCLK,HSE)` sweep
(all 53 decoded preambles reconstruct with zero residual) encodes the
CLKOUT0/CLKFB/CLKIN dividers for any ratio the divider search can solve. Emission
is nevertheless fail-closed to evidence: `--freq` is admitted only for an HSE=8
`SYSCLK` that `check_pll` solves *and* that is silicon-qualified, plus the seven
byte-exact profiles; every other ratio -- including byte-exact-but-unqualified
HSE!=8 sweep points -- fails before synthesis. The generated 164-byte preamble
for each of the seven profiles is still pinned to its retained vendor-oracle hash
in `agamemnon/chipdb/pll_profile_manifest.json`.

The silicon-qualified surface is HSE=8, `SYSCLK` 4-248 MHz. `qualification/pll_freq_evidence.jsonl`
holds 43 silicon-frequency rows: the five HSE=8 profile rates qualified earlier
plus 38 sweep rates promoted now. Each rate is built by the closed-form emitter,
spliced into an SRAM fabric image, and measured on the L48 fixture. Firmware runs
the recovered `SYS_SwitchPLLClock` sequence to select the PLL; the effective clock
is read against the OpenOCD host wall-clock (MTIME counts the system clock, so the
host timer is the only clock-independent reference). OpenOCD resumes for a known
window, halts, and reads elapsed MTIME across a 1 s and a 4 s window; solving
measured = true*(T-offset)/T for both windows yields the true frequency and a
fixed ~26 ms host resume/halt offset. All 38 promoted rates pass, worst 0.058 %
off the requested rate, with the PLL locked and selected and the DAP/SWD link
surviving the halt/readback at every rate up to 248 MHz. `(60,8)` additionally
closes the strict L48 16-bit bus-clock instrument at 60 MHz (110.34 MHz reported
Fmax). `(10,8)` is numerically equal to the 10 MHz HSI reference but is confirmed
PLL-driven by the CLK-register lock/select bits.

This qualifies those HSE=8 output *frequencies* only. `(100,16)` and `(100,12)`
cannot be exercised on the 8 MHz-HSE reference board (they require 16/12 MHz HSE
and would mis-clock), so they remain preamble/timing-qualified only; no other HSE
is claimed. Other PLL outputs, phase, duty-cycle, feedback, and bypass modes are
not qualified and fail closed. The qualified
`examples/firmware/clkcfg_stub.c` temporarily selects HSI for FCB streaming
and restores the selected PLL after lock; `agamemnon sram` itself is a generic
firmware loader and does not perform that transition.

## Packages and IO

Package legality and physical `PIN_n` to IOTILE bond maps exist for
`AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`. L48 is an exact,
silicon-qualified map. The other three are architecture-recovered research
data; strict image emission fails closed for them, and they do not inherit L48
qualification.

The qualified L48 harness maps PIN_25/26/27/28 to Pico
GP12/GP13/GP16/GP17. That mapping is package- and board-specific; it is not a
claim about identically numbered pins on L100, L64, Q32, or another board.

## Hard MCU peripherals

These manufactured MMIO blocks are operated by firmware and consume no fabric.
The results below are non-destructive, SRAM-only runs of the
`examples/riscv_mcu` firmware on the qualified L48 bench, recorded in
[`hard_peripheral_evidence.jsonl`](../qualification/hard_peripheral_evidence.jsonl).

| Peripheral | State | Supported boundary |
|---|---|---|
| CRC-32/MPEG-2 hard unit | Silicon-qualified | Known-answer of ASCII `123456789` == `0x0376E6E7`; no other polynomial, width, or reflection mode |
| DMAC0 memory-to-memory | Silicon-qualified | Single-channel 4-word SRAM copy; no peripheral-linked or descriptor-chained mode |
| UART0 internal loopback | Silicon-qualified | `LBE` loopback echoed byte `0xA5`; no external-pin, baud-accuracy, or flow-control claim |
| UART0 external TX | Silicon-qualified subset | **TX only** on a physical L48 pad (PIN_10) through an open peripheral-route fabric, captured off-chip by an independent logic analyzer: 14 bytes with 11 occurrences of the `00 FF 55 41` stimulus, byte-exact, reproduced across runs. RX, flow control, and the *programmed baud* are unqualified — 9600 was requested and ~560 baud came out, because the UART reference clock is not the value `ag32_pbus_hz()` returns |
| I2C0 master transmit | Silicon-qualified subset | **Framing only** on physical L48 pads (SDA PIN_11, SCL PIN_15): 288 decoded transactions, all `addr=0x55` W, correct START/STOP/address/direction/data phases. The per-byte NACKs are expected — no slave is present. **Requires an external pull-up**; without one the engine stalls and the capture reads flat zero. Reads, ACK against a real slave, clock stretching, repeated START, 10-bit addressing, and the programmed 100 kHz rate are unqualified |
| SPI0 master transmit | Silicon-qualified subset | MOSI/SCK/CSN on physical L48 pads (SCK PIN_12, MOSI PIN_14, CSN PIN_13): 233/233 words all `0x55` plus a `11 22 33 44` payload with 108 matches. **MSB-first, and word boundaries require CS** — without CS the capture decodes as garbage. Also qualifies the sub-word byte-lane fix (the controller shifts the high-order bytes of `PHASE_DATA`, so `ag32_spi_write` left-justifies). RX/duplex, RX lane placement, DUAL/QUAD, DMA, and multi-phase sequences are unqualified; `ag32_spi_init`'s divider argument has no observable effect on SCK (open defect) |
| Watchdog (WATCHDOG0) | Silicon-qualified | Disabled-state register snapshot and a supervised timeout warm-reset with `RST_CNTL` bit30 `SYS_RSTF_WDOG` set exclusively |
| Machine timer interrupt | Silicon-qualified | CLINT/MTIME interrupt taken with `mcause` `0x80000007` |
| RTC | Config path only | `BDCR` `RTCEN`+LSI-select stick and a writable backup domain; the counter does not advance (no low-speed clock), so timekeeping is unqualified |

The UART0-external-TX, I2C0, and SPI0 rows were produced by workbench stimulus
firmware that is **not** part of this repository; their ledger rows name it and
pin its hash, but they are not reproducible from a checked-in source here.

**CAN is not qualified.** No CAN bits have been observed on a wire — the pad
idles recessive-high and this bench has no transceiver. Register-level transmit
activity has been seen, but it is **not recorded in any ledger under
`qualification/`**, so no CAN claim is made. USB host/OTG and the Ethernet MAC
are likewise hardware-gated (host and PHY absent); the hard USB *device* path is
separately qualified through the flash-resident CDC uploader. ADC, DAC, and
comparators are analog blocks reached over the External-AHB window rather than
the MCU-MMIO surface; their observed subset, the vendor-macro caveat, and the
honest negatives are in the fabric-features table above and in
[ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) — note that those bench
results have **no append-only ledger row** yet. No speculative driver is shipped
for anything else here.

Peripheral bit rates in these examples are solved from a *measured* reference
rather than the 248 MHz part maximum, which produced a ~17x baud error when it
was assumed. But there is no single peripheral clock to read out of `CLK_CNTL`:
silicon can report which source and divider are selected, not an absolute
frequency, and the measured domains disagree — MTIME 14.08 MHz, UART0's baud
reference ~14.47 MHz, and SPI0's reference **unresolved**. Only UART0's
reference has actually been measured; I2C0 and CAN0 borrow it as a labelled,
unverified cross-domain assumption. See
[MCU_CLOCKS.md](MCU_CLOCKS.md#measured-default-clock-on-an-sram-loaded-part).

## Bitstreams and programming

| Capability | State |
|---|---|
| LZW decode/encode | Byte-exact for canonical images |
| Raw configuration and CRC | Supported; 99,936-byte raw image with CRC-32/BZIP2 |
| `.agasc` | Lossless named-feature and sparse-raw round trip |
| LUT editing | Supported without rerouting |
| SRAM configuration | Silicon-qualified |
| Main-flash backup, erase, program, and readback verify | Silicon-qualified |
| RV32 MCU-only SRAM execution | Silicon-qualified; signature, DEVICE_ID, misa, and SRAM PC read back over SWD |
| RV32 native/separate flash applications | Silicon-qualified subset; freestanding startup/linkers included, USB-loaded LED app executed at `0x80010000` and its sector was restored byte-exact |
| Pico 2 UART0 ROM programmer firmware and host protocol | Implemented; Pico USB-smoke-tested, target wiring pending |
| Flash-resident USB CDC uploader | Silicon-qualified on L48 for enumeration, identify, read, page erase, write, full readback verification, restoration, and reset |
| Native `--transport usb` CLI | Silicon-qualified for loader 2.1 identify/DEVICE_ID and direct flash read; write/GO use the same unit-tested loader protocol and retain the earlier independent silicon evidence |
| Boot from an existing compressed-config pointer | Silicon-qualified |
| New option-pointer programming | Implemented as explicit opt-in; unsupported for deployment |

SWD hardware commands require a CMSIS-DAP probe and an OpenOCD executable that
implements AGM's `target create riscv -dap` extension. Stock upstream and OSS
CAD Suite OpenOCD builds do not provide that target. Use
`agamemnon install-openocd`, then verify the probe and target with
`agamemnon doctor --probe-dap`. The pinned build and qualification evidence
are documented in [Programming](PROGRAMMING.md).

The UART bootloader uses a Pico 2 and needs no OpenOCD. Its software and
Pico-side bridge are tested, but the target UART link is not silicon-qualified
until the documented harness wires are installed. Native USB ROM boot and USB
DFU class are not implemented. A separate flash-resident CDC ACM uploader is
silicon-qualified on the L48 bench; it is not a recovery path when main flash
is corrupt.

## SERV scope

The shipped SERV examples use a true-dual-port x2 BRAM register file. Hardware
qualification covers continuing instruction fetch/store operation and a
signature workload containing dependent `addi`, `slli`, `xori`, not-taken
`bne`, taken `beq`, `sw`, and repeated backward `jal`.

This is not full RV32I compliance. Other instructions, R-type ADD, exceptions,
CSRs, interrupts, and complete trap behavior are outside the supported claim.
