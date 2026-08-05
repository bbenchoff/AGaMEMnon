# Supported feature matrix

This page defines AGaMEMnon's supported AGRV2K feature set. "Build supported"
means the public flow completes through strict bitgen. "Silicon-qualified"
means the emitted image was exercised by an electrically observable hardware
oracle. FCB configuration acceptance alone is not functional qualification.

The generated [FPGA parity ledger](FPGA_PARITY_LEDGER.md) tracks the same
boundary by encoding recovery, open-flow implementation, silicon state, and
package. It is currently a family-level inventory, not an exhaustive parameter
catalog.

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

Baseline provenance: emitted images are assembled onto
`agamemnon/chipdb/fabric_default.bin`, a 2.8 KB compressed raw configuration.
Open-generated logic and routing bits are overlaid on it and residual baseline
slice bits are cleared. The complete 164-byte global/configuration-chain
preamble is now regenerated from declarative fixed, distribution, and
parametric PLL profiles rather than inherited from that canvas. The canvas
still supplies incompletely decoded non-preamble defaults, so removing it
entirely remains tracked work.

See [the provenance notice](../NOTICE.md) for the licensing and redistribution
boundary around the baseline, derived databases, external tools, and vendor
documentation.

## Fabric features

| Feature | State | Supported boundary |
|---|---|---|
| LUT4 and flip-flop RTL | Silicon-qualified | Combinational logic, registered feedback, counters, shifts, state machines, constants, physical-input registers, and large sequential designs |
| General routing | Silicon-qualified subset | Exact conflict-free physical selectors plus unanimous tile-relative selectors; predicted, conflicting, legacy, or unresolved selectors fail closed |
| Global clock | Silicon-qualified subset | Clock distribution to near and far logic tiles using the listed PLL configurations |
| Physical outputs | Silicon-qualified L48 subset | Characterized header outputs and PIN_25, PIN_26, PIN_27, and PIN_28 |
| Physical inputs | Silicon-qualified L48 subset | PIN_10, PIN_11, PIN_15, and PIN_19; PIN_19 also has a qualified registered path |
| MCU GPIO bridge | Silicon-qualified subset | Four-bit MCU-to-fabric-to-MCU inverter loopback over all input combinations. Exact L48 GPIO5 data/OE lanes 0 and 1 plus input lane 2 are also qualified through pure-open images; the boundary emits coherent inactive `BBMUXS` terminal defaults. No full GPIO-matrix or package-pin claim |
| External AHB read | Silicon-qualified | All 32 fabric-to-MCU data lanes in one simultaneous read |
| External AHB write | Silicon-qualified subset | All 32 MCU write-data lanes in protocol-valid four-bit groups |
| External AHB address | Silicon-qualified subset | Registered isolation of `HADDR[4:2]` through `MCU_DIN76:78`; all eight values observed during a 256-address SRAM sweep. Separate pure-open oracles qualify HADDR[5], a distinct HADDR[3] logic-ingress corridor, and HADDR11 through the x9 AddressA12 route at logical word addresses 0/512 |
| External AHB bus clock | Silicon-qualified subset | Pure-open default `bus_clk = sys_gck` delivery qualifies direct-D sites X14Y11 slice4 through slice7, an eight-state three-bit counter, and a 16-bit LFSR with 500 distinct reads. Across three runs and 45 intervals the LFSR advances exactly one step per undivided 10 MHz MTIME tick. A GPIO4.1-fed synchronous reset held all 16 state bits at zero and re-armed in three runs. Hard `MCU_RESETN`, PLL3 BUSCLK, unrestricted direct-D lowering, and the fourth binary carry cone remain unqualified |
| External AHB constant slave | Silicon-qualified | Constant-ready, OKAY-only combinational endpoint; 32-bit reads return `0x4147414d`, writes complete without effect; no wait/error/register-bank claim |
| External AHB register classes | Silicon-qualified subset | One pure-open image integrates immutable ID low byte `0x4d` at offset 0, reset-zero writable scratch byte at offset 4 over all 256 values, a read-only lower-three-bit counter at offset 8, and one-bit W1C status at offset C. A second image integrates qualified GPIO4.1 synchronous reset. A separate immutable-ID endpoint gives each single aligned word read or ignored write exactly one controlled wait. A third strict image composes one controlled write wait with writable scratch lanes 0–5 and 7; all 256 values match `value & 0xbf`, while unsupported lane 6 reads zero and ignores writes. Real aligned halfword and word instruction classes preserve that low-byte projection with deterministic waits. Strict follow-ons drive HRDATA[14:8] zero while preserving the relocated HRDATA7 exit; HRDATA12 reuses the qualified registered-zero scratch6 source and HRDATA13–14 use free exact GND ingresses. Every upper-lane check through bit14 passed, but exact reads remain unsupported because HRDATA[31:15] is still undriven. The counter has constant nonzero cadence plus phase-swept eight-state coverage and ignores writes. W1C and cross-register preservation pass. Hard `MCU_RESETN`, a full-byte waited bank, the remaining upper-zero response lanes, errors, bursts, and byte semantics remain open |
| Fabric local interrupts | Silicon-qualified routing/cause and integrated command subset | Four distinct sources route simultaneously to `local_int[3:0]`; lanes independently deliver local causes 16–19 with the matching `mip` bit. One strict AHB image uses HWDATA[3:2] to select a one-hot cause and HWDATA[1:0] for mask/ack/set commands. An SRAM-only MCU run counted three exact deliveries per cause, acknowledged each, re-armed twice, held events while masked, and cleared on GPIO reset. On the attached board, post-reset/pre-SRAM-config local `mip` was zero with local `mie` both clear and armed; configured held-reset/released state was also zero. Under the default 10 MHz bus clock, 64 set and 64 acknowledge operations each completed in exactly 21 MTIME ticks and synchronous reset clear took 40 ticks. The state is deliberately shared across the selected lane rather than four simultaneously retained pending bits. Reads return zero; POR, PLL3/alternate clocks, hard `MCU_RESETN`, state readback, and active-pending pre-`mie` visibility remain open |
| Dedicated carry | Silicon-qualified opt-in | Same-tile short chains and one 33-site corridor containing a seed plus up to 32 arithmetic stages |
| BRAM | Silicon-qualified subset | One x18 Port-A path, one x2 Port-B read/control path, all nine X13Y4 read-only x9 data bits through exact per-lane projections, a simultaneous strict-open 256-word x9 identity bundle, and an exact HADDR11/AddressA12 word-0/512 projection; the backend represents independent A/B ports |
| ADC/fabric routes | Build-supported, hardware-unqualified | Distinct read-only ADC0 result bits 0/1 and EOC typed corridors; no ADC configuration or electrical claim |
| PLL | Silicon-qualified subset | `(SYSCLK,HSE)` pairs `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz |
| Timing | Conservative estimate | LUT/FF/carry arcs and worst wire delay per driving mux family; requested failure is fatal |

## Current integration boundary

The 16-node board work is gated by seven ordered integration items. Their
current evidence boundary is:

1. Default External-AHB `bus_clk = sys_gck` delivery is timer-qualified at
   exactly 10 MHz relative to undivided 10 MHz HSI/MTIME. Direct-D feedback is
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
   known MCU-only capture-Q boundary; both remain retained coupled negatives.
   A fail-closed seven-bit replacement ties lane6 to zero and qualifies one
   write wait: all 256 values matched `value & 0xbf`, 128 back-to-back pairs
   passed, ID/W1C/counter/reset remained correct, and the waited loop added
   2578 cycles over SRAM. Hard MCU_RESETN, a full-byte waited bank, bursts,
   and byte/halfword semantics remain open. The
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
   default 10 MHz `MCU_BUS_CLOCK`, 64 set and 64 acknowledge transitions each
   took exactly 21 MTIME ticks; synchronous GPIO reset clear took 40 ticks.
   This is not POR, blank-fabric, flash-content, PLL3/alternate-clock, hard
   `MCU_RESETN`, or asynchronous-reset qualification. Reads intentionally
   return zero; state readback and active-pending pre-`mie` visibility remain
   outside the claim.
3. Fabric-driven output enable and open-drain behavior are not electrically
   qualified. Static input/output support must not be read as bidirectional
   shared-wire support.
4. The PCF-bindable hard-HSE input model is complete, but the complete node
   pinout remains open. Decoded artifacts expose only three independently
   drivable left-edge OE trunks for four link enables; a fourth trunk and an
   unchanged strict build are required before the human wiring gate.
5. Hard-UART TX/RX fabric routes, or a register-bank soft-UART replacement,
   remain unqualified.
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
The remaining high-address range, writes,
other modes/sites, output registers, and collisions remain fail-closed.

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

The device database also contains 14 edges classified by repeated isolated
negative silicon trials. Negative isolated evidence overrides corpus
attribution. Whole-design correlation is not used to classify an individual
edge.

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
writes, output registers, and read/write collision semantics remain
unsupported.

## Timing and PLL

`build --freq MHz` selects the emitted fabric PLL, requests timing closure at
that same frequency, and fails if nextpnr misses the target. Cell timing covers
conservative LUT, flip-flop setup/hold/clock-to-Q, and carry arcs. Wire timing
uses the largest decoded delay for each driving mux family. When no frequency
is supplied by the CLI, project, or environment, the qualified default is
10 MHz.

The timing report is not a complete silicon Fmax model. Exact native wire
class binding, clock skew, IO, BRAM, PLL, package, and broad PVT delays are not
modeled.

PLL emission accepts only the listed `(SYSCLK,HSE)` pairs, and `--freq` fails
before synthesis if the corresponding pair is unsupported. The qualified
`examples/firmware/clkcfg_stub.c` temporarily selects HSI for FCB streaming
and restores the selected PLL after lock; `agamemnon sram` itself is a generic
firmware loader and does not perform that transition. Other PLL outputs,
divider ranges, phase, duty-cycle, feedback, and bypass modes fail closed.

## Packages and IO

Package legality and physical `PIN_n` to IOTILE bond maps exist for
`AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`. L48 is an exact,
silicon-qualified map. The other three are architecture-recovered and emit an
explicit unqualified-package warning; they do not inherit L48 qualification.

The qualified L48 harness maps PIN_25/26/27/28 to Pico
GP12/GP13/GP16/GP17. That mapping is package- and board-specific; it is not a
claim about identically numbered pins on L100, L64, Q32, or another board.

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
