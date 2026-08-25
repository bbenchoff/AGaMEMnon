# Engine-core refactor: design and execution record

**Status: executed.** This refactor completed on 2026-08-06. The design
below was implemented as written, with one extension beyond the original
scope: the architecture-generation side was also delegated per-feature
(`archgen.py` is a 120-line phase driver; each feature contributes its own
wires, pips, and bels), not only the emission side. Final shape: `arch.py`
and `bitgen_seq.py` are seven-line compatibility shims; `bitgen.py` was a
341-line phase-driven driver at completion (2026-08-06; it has since grown
with post-refactor feature admissions); all engine logic lives in the feature modules
under `features/`; every chipdb file has exactly one declared owner; and
bit-ownership write masks are enforced on every build. The migration gate
held throughout: all retained qualified routed artifacts pack byte-identically
through the finished engine, verified on Linux, Windows, and macOS
(`qualification/pack_regression.json`,
`qualification/pack_reproduction_evidence.jsonl`). The C++ nextpnr backend
(`agrv2k.cc`) remains outside this refactor as a declared separate campaign.

The remainder of this document is the design as committed before execution,
retained as the record of what was built and why. Current behavior is
documented in [ARCHITECTURE.md](ARCHITECTURE.md). The refactor changed no
emitted byte, no CLI surface, no evidence record, and no qualified claim.
Byte-identity across the refactor is a migration invariant, not proof that an
arbitrary emitted composition works on silicon; the later campaign's
correctness escapes are tracked in [STATUS.md](STATUS.md).

## Why

`agamemnon/engine/arch.py` (device-database generation, ~2,150 lines) and
`agamemnon/engine/bitgen_seq.py` (routed JSON to raw image, ~1,340 lines, all
logic nested inside one `main()`) jointly implement every supported feature as
hand-threaded special cases. The two files reference roughly 75
feature-specific chipdb CSVs by name, and most qualification commits touch
both files. Three costs follow:

1. Cross-feature bit interference is detected empirically (the ownership
   trace) rather than prevented structurally.
2. Emission ordering is implicit in Python execution order.
3. Admitting a newly qualified corridor requires code edits in shared bodies,
   which caps admission at hand-review rate. The parity program requires
   admission at pipeline rate: data plus claim-tier metadata, zero code.

The registry half of this work is complete: `agamemnon/engine/registry.py`
holds the typed catalog of engine options and silicon constants, each with a
maturity tier and an evidence pointer. This document covers the remaining
structural half.

## Target structure

```text
agamemnon/engine/
  registry.py          # exists: options, constants, maturity, evidence
  chipdb_schema.py     # exists: bounded AGDB loading
  bit_ownership.py     # exists: becomes enforcement (see below)
  features/
    core_logic.py      # LUT/FF packing and slice emission
    routing.py         # selector tables and the clean-edge gate
    clocks.py          # spine, seam, PLL preamble profiles
    physical_io.py     # pads, feeders, edge presentations
    carry.py
    bram.py            # x18/x2/x9 corridors, terminal defaults
    mcu_ahb.py         # HRDATA/HADDR/HWDATA corridors, direct-D
    mcu_gpio.py        # GPIO lanes, inactive-terminal policy
    route_through.py   # identity footprints
  archgen.py           # driver: grid + features -> nextpnr graph
  bitgen.py            # driver: routed JSON + features -> image
  arch.py              # nextpnr entry shim only
```

Each feature module implements one protocol. A feature declares:

- the registry options that gate it;
- the chipdb files it owns (every CSV gains exactly one owner);
- its architecture contribution: the wires, pips, and bels it exposes for a
  given device and package;
- its bitstream contribution: the bits it emits for its placed and routed
  elements, together with the image regions it is permitted to write;
- its emission phase;
- the evidence records that back it, and the claim tier they support.

Adding a qualified corridor then means adding chipdb rows and one entry in the
owning feature's table — not editing shared engine bodies.

## Required properties

**Declared bit ownership is enforced.** Each feature's writable regions are
declared, and bitgen fails the build when a write lands outside the writer's
prepared physical masks or two features actively claim the same bit.
`AGAMEMNON_OWNERSHIP_TRACE` optionally records the resulting last-writer map;
enforcement does not depend on that option. The interference class that
produced the first constant-slave HRDATA failure is now a build error instead
of a silicon experiment.

**Phases are explicit.** The emission order — clear baseline, logic, routing,
clocks, IO, MCU edges, BRAM, preamble, CRC — is named, and features slot into
named phases. `bitgen_seq.py`'s nested-closure ordering is retired.

**Claim tiers gate emission.** The registry's existing maturity field
(release, experimental, archival, diagnostic) extends to the parity program's
claim tiers. Strict bitgen refuses features below the configured tier exactly
as it fails closed today; the tier of every emitted feature is recordable in
evidence.

## The nextpnr constraint

`arch.py` is executed by `nextpnr-generic` with `ctx` and `Loc` injected as
globals; it cannot become an ordinary imported module. It therefore remains
the entry point but shrinks to a shim that calls `archgen.build(ctx, Loc)`.
All real logic moves into importable code that unit tests exercise offline
against a fake `ctx`. This removes the historical hazard that the
architecture half was unverifiable without a built toolchain.

## Migration rule

The refactor proceeds as a strangler migration, one feature at a time, under
one gate:

> After every step, every retained qualified routed JSON must produce a
> byte-identical image.

The mechanism is the existing offline pack test extended to cover all
retained qualification artifacts by SHA-256. Either the bytes match or the
step is reverted. No re-qualification, silicon time, or equivalence judgment
is involved. Steps that cannot be expressed byte-identically (there should be
none) require explicit review rather than a relaxed gate.

## Out of scope

- `agamemnon/engine/uarch/agrv2k/agrv2k.cc`: the C++ backend has its own
  corridor special cases and should eventually consume feature-generated
  tables, but it is a separate campaign after the Python side is settled.
- Any behavior change, flag semantics change (presence semantics are load
  bearing for campaign replay), format change, or claims change.

## Sequencing (as planned; followed)

Land the in-flight HWDATA-fanout and BRAM x9 stream work in the current
structure first; do not restructure under active workstreams. Then execute
this refactor before the differential-fuzzing harness begins admitting
corridors at pipeline rate. This is the order that was executed: the
qualification sprint landed 2026-08-04/05, the refactor completed
2026-08-06, and no differentially derived encoding had been admitted
before the enforcement landed.
