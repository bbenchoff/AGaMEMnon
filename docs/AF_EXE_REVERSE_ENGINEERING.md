# Reverse-engineering `af.exe`: what it is, how we cracked it, and how we think it actually works

This is the narrative companion to [STATUS.md](STATUS.md) and
[VENDOR_PARITY.md](VENDOR_PARITY.md). Those two are the ledger — exactly what is
supported and qualified today. This document is the *story*: what the vendor
back-end is, the reverse-engineering path we took to replace it, and — most
importantly — how our understanding of it changed, including the places we were
confidently wrong and how we found out.

It is deliberately behavioral and methodological. It does not reproduce vendor
binary internals, decompiled source, cipher key material, or private paths;
those stay in the private workbench. What ships here is the understanding.

## 1. The black box

The AG32 is a hard RISC-V MCU welded to an AGRV2K embedded-FPGA fabric. The
sanctioned way to target the fabric is a Windows-only Quartus II fork that drives
a single closed back-end binary, `af.exe`, through the whole flow: pack →
place → route → bitstream generation. There is no Linux path, no open bitstream
format, and no documentation of the fabric's routing or configuration. AGaMEMnon
exists to replace that binary end-to-end with an open flow
(Verilog → yosys → nextpnr → open bitgen → flash), so "IceStorm for the AG32."

`af.exe` itself turned out to be far more ordinary than its opacity suggested.
It is a Quartus-derived tool gated by a plain **license-file check** — no
anti-debug, no self-integrity/anti-tamper. That single fact unlocked the entire
effort: the binary could be run under a debugger and inspected freely.

## 2. How we took it apart

The RE proceeded in layers, each one turning a piece of the black box into open
data or an open algorithm.

**The architecture database and its cipher.** The vendor ships the device
description (routing/mux topology, clock/PLL, oscillator, flash controller,
configuration-chain bit maps) in encoded `.ar` files. These are the master
source of truth. They are wrapped in a **reversible keyed substitution cipher**,
which we recovered — so the databases decode and re-encode with a byte-exact
round-trip. (A memorable trap: the vendor's own decode routine zeroes its input
buffer in place, so the databases have to be recovered from a pristine copy.)

**The bitstream.** The programming image decomposes into leading
configuration-chain records, an FCB (bit-line / word-line) decode stage, an LZW
layer, and a CRC-32. The 164-byte preamble is nothing device-specific or unsafe —
just leading config records — and can be generated from scratch. The upshot: we
can emit byte-exact bitstreams without the vendor binary.

**The routing graph.** The inter-tile switchbox and the intra-tile connection
box both reduce to **closed-form** mappings — edge → configuration selector,
byte-exact across 269,734 edges. This is the finding that made a general open
router possible: it is transcription, not archaeology. A crucial negative came
with it — the dense LUT crossbar's per-node input ordering is **not tabulated in
any file.** `af.exe` computes it procedurally at architecture-load time from grid
geometry. We confirmed this exhaustively (arch files, live-memory walks of the
loaded graph, and decompilation of the build routines), which is why the open
flow reconstructs the mesh from the same geometric rules rather than reading a
table that does not exist.

**The binary itself.** Decompilation mapped the architecture-build and routing
clusters and confirmed the licensing model above. A hardware-breakpoint debugger
let us halt `af.exe` mid-flow and read its live, in-memory routing structures —
useful for validating the closed-form reconstruction against the tool's own
internal state.

**Silicon conduction.** Here is where the AG32 stops being an ordinary FPGA.
A configuration being *legal* — encodable in the bitstream, present in the
routing graph — does **not** guarantee the corresponding wire *conducts* on
silicon. Some config-legal routes are electrically dead. To map this we built
silicon sweeps: force a signal through a candidate edge, read it back through the
MCU, and record whether it toggled. That work produced a catalogue of
"silicon-dead" edges and a hand-validated exit-feeder whitelist, which in turn
drove a conduction-gating policy in the open router: don't let the router use an
edge unless it is observed to conduct.

## 3. How we *thought* it worked — and where that was wrong

For a long stretch, the working model was: conduction death is an **intrinsic
electrical property of the silicon**, `af.exe` must therefore "know" which edges
are usable, and that knowledge lives *somewhere* in the vendor toolchain. We went
looking for it five different ways:

1. an explicit legality/conduction table in the arch files — **not there** (the
   global-track records are clock/PLL/reset/SEAM only; the RMUX mesh appears
   nowhere as data);
2. a legality table inside `af.exe` — **not there**;
3. `af.exe` itself as an oracle (does it *refuse* a dead edge?) — **no**; it
   routes config-legal-but-dead edges into real bitstreams;
4. a per-edge companion/enable bit `af.exe` emits that we omit — **no**; our
   bitgen already emits byte-identical per-edge configuration;
5. `af.exe`'s routing cost model — **global-schedule only**, no per-resource
   term, so it cannot encode per-edge conduction.

From those five negatives we concluded, more than once and with more confidence
than the evidence warranted, that conduction was an unrecoverable intrinsic
silicon property and the matter was settled. **That conclusion was wrong**, and
the way it was wrong is the most important part of this story.

## 4. How we think it works now

`af.exe` is, in current understanding, a **PathFinder-style negotiated-congestion
router** — delay- and criticality-weighted, with a *global* cost schedule (the
present-congestion / delay-ratio / reroute schedule that lives in the vendor's
fitting settings). It builds a **uniform, geometric** routing mesh and routes
designs across it. It carries **no per-edge conduction model at all.** It is,
in effect, **conduction-blind**: it will happily route an electrically dead edge,
and it does so routinely. Vendor bitstreams work not because the tool avoids the
dead edges knowingly, but as a **selection effect** — the designs anyone has ever
verified on silicon are small and spatially local, so they never generate the
long far-tile-to-MCU routing need that lands on the marginal edges.

And then the reframe that is still, as of this writing, being nailed down:

> **The "dead" edges were, at least in part, an artifact of our own
> characterization method — not the silicon.**

Our sweeps forced a signal onto a specific feeder by **blacklisting its
alternatives**. That strip of the surrounding routing is, apparently, what killed
conduction — not the edge itself. When the same edge is routed *in its natural
context* — by `af.exe`'s own free router, or even by our own router with the
blacklist removed — it **conducts**. We proved this on silicon: an
`af.exe`-native bitstream carrying a live toggling signal through a catalogued
"silicon-dead" edge reads as *toggling*, reproduced across independent runs with
a valid control lane.

The implication is large, if it generalizes: the routing wall we spent so long
treating as a hardware limit was substantially **self-inflicted**. The data — the
full routing graph — was in hand the whole time. What held the open flow back was
our *belief* that a big part of that graph was dead, encoded as an over-restrictive
gate.

**Confidence, stated honestly.** As of this writing the reframe is board-verified
for the first edge(s) only, with independent reproduction and a valid control.
Two experiments are in flight to turn "promising" into "known": a
placement-aimed sweep to measure how much of the dead catalogue is artifact
versus real across the whole set, and a forced-vs-native bitstream differential
to pin exactly which surrounding configuration the blacklist strips. Until those
land, this section is the best current model, not a settled result — a distinction
this project has learned to take seriously.

## 5. What the story is really about

Three lessons, which are the honest through-line:

- **Config-legal is not conducting — but *how you force a test* can manufacture
  the very deadness you are measuring.** A characterization-method artifact can
  masquerade convincingly as a silicon fact. "Only silicon proves a placement" was
  a hard-won rule; its necessary companion is "and the way you drove that
  placement is part of what you measured."
- **`af.exe` is not magic.** It is a conduction-blind, geometry-driven,
  negotiated-congestion router whose reliability is a selection effect of small
  local designs. That reframes vendor parity itself: less a matter of missing
  vendor knowledge, more a matter of our own gates.
- **Stated certainty is cheap and was repeatedly wrong here.** The turning points
  in this effort were not clever deductions; they were purpose-built vehicles read
  on real silicon with valid controls. Every time a confident conclusion collapsed,
  it collapsed against a measurement, not an argument.

The open toolchain that ships in this repository is the durable output. This
document is the map of how we came to understand the thing it replaces — including
the wrong roads, which for a reverse-engineering project are most of the map.
