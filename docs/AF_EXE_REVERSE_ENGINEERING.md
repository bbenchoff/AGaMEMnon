# Reverse-engineering the AG32 fabric back-end

This is the narrative companion to [STATUS.md](STATUS.md) and
[VENDOR_PARITY.md](VENDOR_PARITY.md). Those pages define the support and parity
boundary. This page explains how the open flow was recovered, which early
theories were wrong, and why AGaMEMnon now treats encoding, routing, and silicon
behavior as separate kinds of evidence.

It does not reproduce decompiled source, vendor binaries, private paths,
license material, or private workbench artifacts. The public result is the
behavioral understanding, recovered data with disclosed provenance, open
implementation, and normalized qualification evidence.

## 1. The black box

The AG32 joins a hard RISC-V MCU to an AGRV2K embedded-FPGA fabric. The vendor
flow drives a closed Windows back-end through packing, placement, routing, and
bitstream generation. No public description explains the routing mesh,
configuration fields, or image format.

AGaMEMnon's objective is an open path:

```text
Verilog -> Yosys -> nextpnr -> open bitgen -> SRAM/flash image
```

The closed tool remains a valuable experimental instrument. It is not shipped,
called by the public flow, or treated as an infallible functional oracle.

## 2. What was recovered

### Architecture data

The vendor device descriptions contain routing/mux topology, clock and PLL
records, oscillator and flash-controller data, and configuration-chain maps in
encoded archives. The archive transform was recovered with byte-exact
decode/re-encode checks. Parsed data is normalized into reviewable chip-database
tables rather than loaded from the closed executable at build time.

### Image format

The programming image separates into configuration-chain records, the fabric
body, compression, and CRC. The 164-byte preamble is made of configuration
records rather than an opaque executable-produced token. AGaMEMnon now
generates the preamble, design-neutral body, admitted feature overlays,
compression, and CRC openly. The generated body is byte-exact to the decoded
reference canvas; the retained canvas is non-loadable and exists only as a
decode/differential anchor.

That is a format and base-generation result. It does not establish the
functional meaning of every reserved field or prove every overlay correct.

### Routing selectors and geometry

Much of the regular routing fabric reduces to measured geometric rules and
selector observations. Two closed-form classes reproduce every observation in
their respective corpora. Other classes are admitted only from exact physical
or unanimous tile-relative evidence; conflicts are preserved and refused.

A notable negative result was important: the dense LUT crossbar input ordering
is not simply tabulated in a device file. It is constructed procedurally from
geometry. The open architecture reconstructs it rather than searching for a
table that does not exist.

The resulting database is large, but its denominator matters. “Rows recovered
from the observed corpus” is not “percent of every route on the chip.” Special
feeders, unseen positions, placement feasibility, and composition-level
behavior remain separate questions.

### Hard blocks and boundaries

Differential builds and silicon vehicles recovered bounded fields and routes
for the PLL, BRAM, IO ring, MCU External-AHB boundary, local interrupts, and
hard-peripheral-to-pad connections. These features are deliberately exposed as
exact profiles or typed primitives. A decoded register or cell field is not
promoted until its public interface, pack behavior, and evidence tier agree.

## 3. The conduction false start

Early silicon sweeps found routes that were legal and encodable but whose
signals appeared stuck. The working theory became: individual routing edges
were intrinsically dead, and a safe router needed a per-edge negative table.
The team searched architecture files, executable data structures, companion
configuration fields, and routing costs for a hidden legality model. None was
found.

The negative catalogue was still compelling because the large sweep produced
repeatable failures. The missing insight was that the experiment had measured
a whole congested composition while assigning the failure to one nominated
edge.

Matched isolated vehicles reversed the conclusion:

- the same nominated edge conducted in a naturally routed vendor image;
- it conducted in a naturally routed open image;
- it also conducted when the open router was forced through that exact hop;
- matched forcing controls showed that a negative forced result could be an
  artifact of the surrounding construction;
- direct pad-to-pad witnesses eventually established positive conduction for
  all 14 edges in the historical negative catalogue.

The production negative set is therefore empty. The exact historical result is
not “all routing conducts.” It is:

> The 14 per-edge negative classifications were invalid because congested-
> context failures were attributed to individual edges. All 14 edges conduct
> in bounded isolated witnesses.

The aggregate failure remains real. Wide designs can still fail to route, and
large composed images can still behave incorrectly. Per-edge un-gating removed
one mistaken restriction; it did not solve wide placement, corridor pressure,
clock distribution, or density-dependent execution.

The chronological experimental record is preserved in
[CONDUCTION_REFRAME_STATUS.md](CONDUCTION_REFRAME_STATUS.md).

## 4. The broader parity campaign changed the question

Once selector coverage and small exact paths improved, the project tested 105
hand-authored boundary designs under model/vendor/open comparison. The result
was not a smooth approach to “full parity”:

| Outcome | Designs |
|---|---:|
| Narrow parity success | 25 |
| Vendor reference failed or unstable | 12 |
| Open-flow routability gap | 52 |
| Open-flow correctness escape | 13 |
| Harness incomplete | 3 |

Only 6 of 51 paired structural forms passed. The sealed holdout set was n=0.

This campaign exposed three independent limits.

### The vendor is an encoding witness, not behavioral truth

Some vendor images failed their independent models; others were unstable.
Vendor routes remain excellent evidence for topology, placement precedent, and
selector/configuration codewords. Their behavior still requires an external
contract and an observable silicon oracle.

### A strict clean image can still be wrong

Several open images had zero unmapped, predicted, or legacy selectors,
repacked byte-identically, and matched a routed logical evaluator, yet failed on
silicon. Examples include initialized BRAM reads returning zero, PIN_10/PIN_12
input compositions staying low, SPI0/SPI1 MISO staying high, five far-spread
registers losing state, and a 256-bit design diverging at transaction two.

This does not make strict accounting useless. It eliminates known ambiguity and
makes failures localizable. It does mean the phrase “strict build” must never
be expanded into “silicon-correct design.”

### Equivalent logic forms do not have equivalent feasibility

Ordinary RTL and explicit-primitive versions often synthesized, placed, and
routed differently. In several families one form passed while the other never
emitted an image. Wide `regbank16`, `addsub16`, and 256-bit state vehicles now
bound a placement/routing frontier that cannot be solved by importing another
selector row.

## 5. The current model

AGaMEMnon now separates five layers:

1. **Representability:** the image field and its encoding are understood.
2. **Admission:** the public policy permits that exact feature/selector.
3. **Routability:** placement and routing can construct a legal image under the
   frozen rails.
4. **Logical correctness:** synthesis/adapters/routed-netlist evaluation match
   an independent model.
5. **Physical correctness:** the exact image passes an observable contract on
   identified silicon with valid controls.

Support is never inferred upward. Layer 5 evidence for one composition does
not qualify a neighboring route, mode, pad, width, or package.

The release response to a known escape is fail-closed where the trigger is
identifiable. Typed SPI0/SPI1 MISO and the affected initialized-BRAM profiles
now refuse with defect IDs. Other escape artifacts remain excluded while their
general triggers are investigated. This is an honest partial defense: the open
flow cannot yet recognize every composition that might be silently wrong.

## 6. What works now

Strong exact results include the openly generated base image; bounded L48 LUT,
state, carry, routing, AHB, interrupt, IO, PLL, BRAM, and programming profiles;
and the campaign's UART0/1/2 TX, SPI0/1 TX, and I²C0/1 repeated-START
transactions. The normalized evidence gate validates 64 ledgers / 653 records.

Those results are useful precisely because their exclusions are explicit. They
do not amount to arbitrary Verilog support, broad peripheral support, a
statistical parity rate, other-package silicon qualification, or a guarantee
that every accepted image behaves correctly.

## 7. What remains

The next hard problems are composition-level:

- identify and guard the open correctness-escape triggers;
- make wide MCU/fabric state place and route repeatably;
- recover the missing BRAM read/static and physical-input configuration;
- explain far-site clock/state and density-dependent failures;
- broaden UART RX, SPI RX/duplex, I²C modes, IO electrical behavior, and the
  remaining hard peripherals;
- create a genuinely sealed holdout suite after the rules are frozen;
- qualify other packages on their own hardware.

The central lesson is not that the closed tool is simple or that silicon is
unreliable. It is that no single oracle is enough. Architecture data can prove
encoding, the vendor can prove precedent, a logical evaluator can prove the
routed Boolean model, and only a controlled board observation can prove the
exact physical composition tested. AGaMEMnon's durability comes from keeping
those statements separate.
