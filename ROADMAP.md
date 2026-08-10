# Roadmap

This file lists open work only. Current public support belongs in
[docs/STATUS.md](docs/STATUS.md); completed experiments and artifact hashes
belong in the append-only qualification ledgers.

AGaMEMnon prioritizes reproducible first use, recovery safety, and bounded
hardware evidence over broad but unqualified coverage.

## Immediate priorities

The release-pivot directive makes the installable L48 tool the near-term
driver. The 16-node/TDMA board remains a later integration program and does
not define this release's completion.

1. Integrate or deliberately rework the workbench-complete MCU AHB result.
   The silicon evidence closes a complete-byte waited bank, exact 32-bit
   reads, aligned byte/halfword semantics, and SINGLE-only handling, but its
   implementation commit is not in current public main. Until it is ported
   through the refactored engine and all release gates pass, public support
   remains the seven-bit waited image. Hard `MCU_RESETN`, alternate bus
   clocks, generic direct-D lowering, broader state, and deterministic
   HRESP-to-MCU faults remain outside the claim.
2. Finish publication, not just preparation: choose the final candidate,
   obtain green hosted wheel/archive gates, publish signed/hash-sidecar SDK
   artifacts, and independently reproduce a downloaded artifact. Existing
   `v0.1.0`/`v0.1.1` tags are not substitutes for a Releases-page artifact.
3. Scale reviewed routing admission beyond the six experimental RMUX30 rows.
   R2 witnessing is closed at 71,697/71,697, but witnessed occupancy must not
   become default selector support without the approved population dossier,
   holdout, exception, and evidence-tier gates.
4. Convert the 39 admitted BRAM configuration rows into behavioral support
   only where independent tests justify it. Priority gaps are writes, byte
   enables, output registers, width/mode composition, independent clocks,
   collision/read-during-write behavior, high-address breadth, and sites
   beyond the bounded X13Y4 read proof.
5. Broaden PLL support past seven complete fixed profiles only after legal
   combinations and silicon/timing behavior are proven. Phase, duty,
   feedback, bypass, other outputs, and general oscillator/HSI selection are
   still absent.
6. Expand exact timing beyond the 542 local patterns while retaining the
   conservative floor. Add clock skew and hard-block, IO, BRAM, PLL, package,
   and PVT models before making any sign-off/Fmax-equivalence claim.
7. Remove the inherited non-preamble configuration canvas and prove a fully
   from-scratch image and deployment-safe boot/option-pointer path.
8. Treat Q32/L64/L100 silicon qualification, IO electrical fixtures, and the
   16-node board as hardware-gated follow-on work. Recovered maps and clean
   builds do not transfer L48 evidence.

## Vendor-toolchain parity program

The long-horizon goal past the 16-node board is parity with the vendor flow:
any design the Quartus-fork/`af.exe` path can build, and any capability the
silicon exposes, should be buildable and qualifiable through AGaMEMnon. This
section frames that program and the techniques for it. It generalizes several
FPGA-flow items below, which remain the bounded next steps; the ordered board
items above are unaffected.

### Position update (2026-08-10)

The program is running. Since the 2026-08-05 baseline below: the engine
refactor prerequisite is complete (feature modules, enforced bit ownership,
seven-line shims; every retained artifact byte-identical, reproduced on
three operating systems); the differential harness, coverage-targeted
generation, ownership-attributed diffing, and candidate store are built and
operating in the workbench; an exact vendor route-replay steering mechanism
was demonstrated, making arbitrary-edge witnessing constructive rather than
probabilistic; the claim-tier policy is implemented and published in
[docs/CLAIM_POLICY_LEDGER.md](docs/CLAIM_POLICY_LEDGER.md); the register-bank
silicon instrument is qualified end-to-end; and a frozen routing-target
ledger separated the true witnessing frontier from topology-model phantoms.
R2 witnessing is now closed: all 71,697 live target rows are witnessed, with
42,297 phantom and 14 silicon-dead rows terminally accounted. This is not
vendor equivalence, silicon conduction, or selector-table promotion. Six
reviewed RMUX30 rows are admitted to public data at `experimental-strict` and
remain disabled by default; population-scale admission remains open.

### Measured baseline (2026-08-05)

Reproducible from the shipped `sel_edge_pairs.agdb` metadata and key space:

- The recovery corpus observed 733,862 absolute edge keys; 659,759 (90%)
  decoded to consistent selector encodings and ship in the release tables.
  The ~74,000 rejected keys are a conflict rate *within the observed slice*,
  not a device-coverage figure.
- 21,752 destination RMUX/IMUX instances across 159 of the 322 grid tiles
  carry at least one clean edge. Roughly half the grid has no release routing
  at all.
- Covered muxes average ~30 clean input edges against a 12-bit two-hot
  selector space, with a median of 17 distinct observed encodings per mux, so
  even covered muxes retain unobserved legal inputs.

Coverage is corpus-shaped, not designed: the gaps concentrate in regions no
shipped vendor design exercised. The recent silicon negatives — inactive
`BBMUXS` terminals, identity route-through footprints, the missing fourth OE
trunk, the HWDATA fanout wall — all live in that blind spot.

Axis summary: LUT/FF core logic is the broadest supported surface; general
routing remains sparse by device coverage despite the large observed corpus;
IO-ring decode is much broader than electrical qualification; PLL emission is
seven fixed complete profiles in a large parameter space; BRAM behavior is a
bounded X13Y4 read subset despite 39 experimental configuration encodings;
the final workbench AHB result awaits public-main integration while fabric
master and DMA remain open; no general hard-peripheral remap surface exists;
timing is mostly conservative fallback; and one of four packages is
silicon-qualified.

The staged execution order this baseline prescribed (qualify on the old
engine first, land byte-neutral foundations, split last) was followed and
completed on 2026-08-06; the executed design and migration record are in
[docs/ENGINE_REFACTOR.md](docs/ENGINE_REFACTOR.md).

### Why the current method cannot finish this

Corridor-at-a-time qualification — one bounded claim, one bench oracle, one
retained record — built the project's trust and costs roughly one bench
session per corridor. The parity surface is tens of thousands of corridors.
Parity requires converting decode and qualification from hand experiments
into automated pipelines without weakening the fail-closed release boundary.

### Technique 1: differential harness against the vendor back-end

- [x] Stand up a scripted `af.exe` environment (Windows VM or Wine) that
  builds generated netlists unattended.
- [x] Generate constrained-random legal netlists targeting uncovered tiles,
  uncovered muxes, and covered muxes' unobserved inputs; build each design
  with both flows.
- [x] Diff open and vendor images feature-by-feature using the ownership
  trace; record agreements as candidate encodings with full provenance.
- [ ] Arbitrate divergences on silicon before admitting either encoding.
- [x] Define the fuzz-scale evidence policy: the current rule that
  whole-design correlation never classifies an individual edge is correct for
  a hand-curated corpus; decide the statistical threshold at which repeated
  independent agreeing differential builds admit an edge, and record that
  threshold with the claim.
- [ ] Refeed the ~74,000 conflicted keys and 2,393 zero-selector samples
  through the pipeline with fresh targeted corpus rather than discarding
  them.

### Technique 2: self-hosted silicon test instrument

- [x] Once the sequential register bank closes, build a fabric test-harness
  wrapper that exposes device-under-test state to firmware over External AHB.
  The register bank is not just a board gate; it is the instrument that makes
  mass qualification cheap.
- [ ] Replace pin-level Pico sampling with firmware-reported oracles for
  qualification classes that do not electrically involve pads: routing
  conduction, BRAM modes, carry corridors, clocking state.
- [ ] Put one L48 board into hardware-in-the-loop CI: nightly flash-and-report
  sweeps that walk the parity matrix and append machine-generated evidence
  records under the same hash discipline as hand-run experiments.
- [ ] Keep pad-level electrical claims (IO attributes, OE/open-drain, drive
  current) on the external-probe path; the instrument cannot self-observe its
  own pads.

### Technique 3: tiered claims

- [x] Promote the parameter-manifest distinction (declaration / candidate /
  backend-accepted / open-supported / behavior) into an explicit release
  claim tier: decoded → differentially validated → statistically
  silicon-validated → individually qualified.
- [x] Gate strict bitgen by tier; everything below the configured tier fails
  closed exactly as today. The default release tier stays individually
  qualified until the differential pipeline has earned trust.
- [x] Emit the tier per feature in the generated parity ledger so the
  boundary stays public and auditable.

### Technique 4: routing-graph closure

- [ ] Use the tile-relative selector scheme to *predict* encodings for the
  163 uncovered tiles; validate predictions through the differential harness
  and instrument rather than shipping predictions as clean.
- [ ] Track closure as a measured percentage of destination-mux coverage, not
  as a feature list; regenerate the numbers above as the pipeline runs.

### Prerequisites

- [x] Execute the deferred `arch.py`/`bitgen_seq.py` de-tangling (complete 2026-08-06) before
  pipeline-scale corridor admission; every technique above lands code in both
  files, and the entanglement is already the review bottleneck at hand-run
  velocity. The committed end-state design — feature modules with declared
  chipdb ownership, enforced bit-ownership regions, named emission phases,
  and a byte-identical strangler migration over the retained artifacts — is
  specified in [docs/ENGINE_REFACTOR.md](docs/ENGINE_REFACTOR.md).
- [x] Extend the evidence tooling so machine-generated records carry the same
  provenance, hashing, and append-only discipline as hand-run records.

### Sequencing

Differential harness → register-bank instrument → routing closure → IO-ring
qualification (decode is largely done; this is labor) → BRAM and PLL
matrices → named peripheral remap routes (the capability that justifies the
chip) → native timing model → Q32/L64/L100 packages → SDK breadth → the
from-scratch image as the closing proof that the model is complete.

## Downloadable SDK

- [ ] Publish pinned Windows and Linux archives containing AGaMEMnon, Yosys,
  AGRV2K nextpnr/runtime, RISC-V GCC, examples, licenses, and SBOMs.
- [ ] Publish SHA-256 sidecars and exact source/build provenance for each
  hosted artifact.
- [ ] Independently download and reproduce the offline diagnostic, MCU build,
  strict FPGA+MCU build, bitgen, and hardware-free programming-plan smoke on
  both hosts.
- [ ] Decide and state whether each archive is build-only or includes the
  paired qualified OpenOCD programming tool.

## MCU SDK

- [ ] Grow open drivers for RTC, flash, CAN, USB, ADC, DAC, comparators,
  Ethernet, and fabric/DMA request use cases.
- [ ] Add non-destructive qualification programs and evidence for each
  supported hard peripheral.
- [ ] Qualify supervised watchdog behavior and the existing DMA/CRC candidates
  before promoting their runtime claims.

## FPGA flow

- [ ] Decode and emit every required non-preamble reset/default field instead
  of inheriting the remaining tile-grid canvas.
- [ ] Broaden BRAM modes, sites, initialization, writes, output registers, and
  collision behavior. All nine X13Y4 read-only x9 data bits are qualified over
  their exercised address projections, q4/q5 are qualified simultaneously on
  one exact paired route, and HADDR11/AddressA12 is qualified at word
  addresses 0/512. A simultaneous strict-open output bundle also returns all
  identity values 0..255 exactly once. Next are the remaining high-address
  lanes/range.
- [ ] Expand dedicated-carry seed/spill corridors and multi-chain placement.
- [ ] Replace conservative mux-family timing bounds with native wire, skew,
  IO, BRAM, hard-block, package, and PVT models.
- [ ] Hardware-qualify Q32 first (the 16-node board package), then L100 and
  L64 independently.
- [ ] Complete the unfinished MCU/fabric items in
  [docs/MCU_FABRIC_ROADMAP.md](docs/MCU_FABRIC_ROADMAP.md).

## Persistent deployment and recovery

- [ ] Qualify option-byte programming with complete backup, power-cycle,
  readback, restoration, and flash-independent recovery evidence.
- [ ] Prove uncompressed boot from a fully open-generated image on a blank or
  restored device.
- [ ] Complete target-side qualification of the Pico UART mask-ROM transport,
  including interrupted erase/program recovery.
- [ ] Keep the flash-resident USB uploader explicitly separate from recovery
  transports in every command and document.

## Community qualification

- [ ] Add independently reproduced boards, probes, transports, clocks, and
  tool versions to the qualification records.
- [ ] Replace the historical malformed PIN_26 hash exception with a fresh
  retained-artifact qualification record rather than editing history.
- [ ] Keep support claims, packaged behavior, README, status matrix, and all
  active roadmaps synchronized for each release candidate.
