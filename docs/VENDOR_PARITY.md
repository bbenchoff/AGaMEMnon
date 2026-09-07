# Vendor parity: measured boundary

AGaMEMnon does not currently have broad vendor parity. It has a collection of
exact, independently checked silicon results and a larger, now well-classified
frontier. This page records the 2026-08-24 controlled campaign without turning
its hand-authored sample into a population claim.

## Closed campaign snapshot

| Verdict | Count | Meaning |
|---|---:|---|
| `PARITY_SUCCESS` | 24 | Model, usable vendor ensemble, and open silicon result agreed within the fixed contract. |
| `PARITY_SUCCESS_AFTER_FIX` | 1 | Same result after a defect was isolated, repaired, and rerun. |
| `VENDOR_REFERENCE_FAIL` | 10 | The vendor image was unusable or disagreed with the independent model, so it could not define parity. AGaMEMnon may independently pass or fail the model. |
| `VENDOR_UNSTABLE` | 2 | Vendor behavior was not stable enough for a parity reference. |
| `ROUTABILITY_GAP` | 52 | AGaMEMnon did not emit a qualifying image under the frozen rails. |
| `CORRECTNESS_ESCAPE` | 13 | A clean open image failed the model-backed silicon contract. |
| `HARNESS_INCOMPLETE` | 3 | Apparatus/control requirements failed before a valid classification. |
| **Total** | **105** | Hand-authored development vehicles. |

The sealed holdout denominator was **n=0**. No confidence interval, success
rate for unseen RTL, or claim about “percent of vendor parity” follows from
these counts.

## What counted as parity

A parity success required all applicable layers:

1. a preregistered input/output contract and independent expected model;
2. adapter agreement between ordinary RTL, explicit structural form where
   present, vendor ABI, and open primitives;
3. multiple fresh vendor seeds that were stable and matched the model;
4. a release-strict open build with exact selector/config accounting;
5. a control-first, SRAM-only board session on the identified L48 target;
6. repeated exact functional observations and final reset/restoration.

Vendor/open image bytes were not required to match: different legal placement
and routing can implement the same behavior. Conversely, a byte-identical open
repack or exact routed simulation did not count as functional parity without a
passing silicon oracle.

## Positive results

### Paired structural forms

Six of 51 structural forms passed together with their ordinary/user forms:

| Surface | Exact qualified contract |
|---|---|
| SPI0 TX | Mode 3, MSB-first, active-low CS, 1–4-byte cycles; documented dividers; direct raw TX-register byte-order semantics; exact L48 pad route |
| SPI1 TX | Independent controller, same bounded mode/cycle/divider and raw-byte-order boundary on its exact L48 route |
| I²C0 | Address `0x55`, write `2A A6`, repeated START, read `5A C3 7E`, ACK/ACK/NACK, STOP; exact PIN_11/PIN_15 open-drain route; one separate four-point 500 us stretch profile |
| I²C1 | Same fixed transaction on the independent controller and exact PIN_11/PIN_15 route; no stretching claim |
| UART1 TX | Fixed 64-byte `FF 55 41 00` pattern, 8-N-1, nominal 9,600/38,400/115,200 baud, exact PIN_10 DATA/OE route |
| UART2 TX | Fixed 64-byte `C3 3C 5A A5 00 FF 81 42` pattern, 8-N-1, nominal 9,600/38,400/115,200 baud, exact PIN_10 DATA/OE route |

### Other narrow successes

- UART0 TX/PIN_10 passed only after correcting one exact selector codeword;
  this is `VP-AGM-002`, narrowly closed.
- Selected model-backed small fabric/AHB vehicles pass: a Boolean handshake,
  two- and four-bit shifts, exhaustive two-bit add/subtract, one dual-LFSR4
  form, one shared-mode depth/fanout form, and selected exact MCU-entry and
  interrupt compositions.
- Exact physical-output vehicles on PIN_12 and PIN_16 pass their fixed held
  output schedules.
- One matched PLL/shift point passes. It does not generalize to far-site clock
  distribution.

The exact list, hashes, seed sets, routes, and board transcripts live in the
normalized `qualification/*.jsonl` records and their checked-in artifacts.

## What failed, and why it matters

### Routability dominates the denominator

Fifty-two designs ended without an admissible image. Some explicit structural
rewrites failed where semantically equivalent ordinary RTL passed; other
families failed at both low and higher utilization. These are honest graph,
placement, corridor, or router limitations. They are not silently counted as
parity failures and are not repaired by enabling research selectors, extending
timeouts indefinitely, or pinning a one-off route.

The widest bounded results are especially important:

- X13Y12 ingress coverage is no longer the limiting issue;
- `regbank16` still produces no image downstream;
- `addsub16` exposes placement divergence near the intended density policy;
- a 256-bit user-state design routes only after 12 failed attempts, then fails
  functionally; its structural rewrite does not route.

### Correctness escapes invalidate simple “strict means correct” reasoning

Thirteen vehicles emitted clean images but did not satisfy their silicon
contracts. The tracked families are:

- MCU feedback, FSM update, rotate/reset, and add/reset compositions
  (`VP-AGM-001`, `003`–`005`);
- initialized x1 and x18 BRAM reads returning zero despite the expected INIT
  and currently modeled BRAM config fields (`VP-AGM-006`);
- five far-spread registered sites returning zero despite a correct routed
  logical model (`VP-AGM-007`);
- PIN_10/PIN_12 physical ingress returning only low and independent SPI0/SPI1
  MISO paths returning `0xffffffff` (`VP-AGM-008`);
- a 256-bit architecture-stress vehicle matching transaction one and diverging
  at transaction two while its routed evaluator remains exact (`VP-AGM-009`).

The historical production response refused typed SPI0/SPI1 MISO and the
demonstrated affected BRAM profiles. SPI receive admission has since been
repaired and qualified on the work branch; see
[SPI receive qualification](SPI_RECEIVE_QUALIFICATION.md). Known bad SPI
images remain rejected; the blanket typed-MISO refusal is removed.
Artifacts for the other escapes remain outside the qualified set while a
general trigger and remedy are developed. This is mitigation, not proof that
all neighboring silent-wrong compositions can already be recognized.

For the demonstrated set, containment is **RELEASE-SAFE** and met: byte-exact
and route-independent fingerprint fences refuse all 13 benchmark negatives,
with zero fingerprint collisions across 73 retained routes. The separate
root-cause campaign remains hardware-gated at 0/13 fully root-caused. That
incomplete causal account is not an unsafe release state; unsupported new
compositions still fail closed or require their own silicon qualification.

### The vendor is not an infallible functional oracle

Ten vendor references failed and two were unstable. In at least one campaign
vehicle the independent model and AGaMEMnon agreed while the vendor did not; in
another, model, vendor, and AGaMEMnon produced three different outcomes. Vendor
routes remain valuable encoding and topology witnesses, but parity requires a
separate behavioral contract. A vendor disagreement is not automatically an
AGaMEMnon defect or a vendor defect until the independent layers isolate it.

## Public support versus research knowledge

The public flow contains large recovered selector/configuration corpora and a
fully regenerated design-neutral base. Those facts describe what can be
represented, not what arbitrary designs can do on silicon.

For the historical per-edge conduction denominator: **Current production
count: 14 of 14 admitted; 0 conservatively blocked as unverified.** All 14 old
negative rows gained bounded positive witnesses; this does not make the whole
routing graph or wide congested compositions qualified.

| Layer | What is established | What remains open |
|---|---|---|
| Image format | Container, decompression/compression, CRC, preamble, and generated base/overlay mechanics for admitted features | Functional meaning of reserved/unnamed fields and every unsupported hard-block mode |
| Routing encoding | Large exact physical and unanimous-relative selector sets with conflict rejection | Whole-device topology/selector coverage, special feeders, and broad routability |
| Routing conduction | Many exact routes and former “dead edge” candidates pass in isolated constructions | Congested/wide compositions and arbitrary path conduction |
| Placement | Exact retained profiles and many small fresh vehicles | Robust wide/dense placement and user/structural equivalence |
| Functional silicon | The exact positive contracts above and earlier bounded qualification ledgers | General RTL, BRAM, clock reach, ingress, peripheral breadth, CPU-scale fresh routes, and other packages |

`research-unsafe` exposes additional vendor-derived, conflicted-majority, or
predicted knowledge with a provenance sidecar. It is for investigation only.
It does not widen release qualification, provide a missing silicon oracle, or
turn a no-image result into parity.

## How to cite a result

State all of the following:

- part/package and board;
- exact design/profile and mode;
- route/pin/clock boundary;
- model and vendor-reference status;
- number and kind of repeated silicon observations;
- explicit exclusions.

Good: “The exact L48 UART2 TX/PIN_10 composition emitted a fixed 64-byte 8-N-1
pattern in nine open captures across three nominal baud settings after its
vendor ensemble passed.”

Not supported: “UART2 works,” “strict images cannot fail,” “25/105 designs prove
24% vendor parity,” or “the open flow supports arbitrary Verilog.”

See [STATUS.md](STATUS.md) for the release boundary and
[ROADMAP.md](../ROADMAP.md) for the prioritized frontier.
