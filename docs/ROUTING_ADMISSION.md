# Routing admission: which edges AGaMEMnon will route through, and why

Every routing edge AGaMEMnon offers to the router has to clear two independent
questions, and it is worth keeping them apart because they fail in completely
different ways:

1. **Does this wire conduct here?** If it does not, the design routes on paper
   and the signal dies on silicon. Loud, local, and diagnosable — a lane reads
   stuck.
2. **Do we know the codeword that programs this mux input?** If we do not, the
   bitstream is well-formed, the chip accepts the configuration
   (`FCB_STAT 0x000f0002`), and *a different input is selected*. Quiet,
   non-local, and historically the most expensive class of bug in this project.

A single binary gate — admit an edge only if some record witnessed it *at its exact position* — is
safe, but it conflates the two questions and refuses a large set of edges whose
codeword is known exactly and which have simply never been watched conduct.
The closed reference backend does the opposite: it carries no conduction model at
all, routes marginal edges without hesitation, and tells the user nothing.

There is also a third, composition-level question: **does the complete routed
and configured design behave correctly on silicon?** Edge witnessing and exact
codewords do not settle clock delivery, hard-block static fields, physical pad
chains, density effects, or interactions among many individually acceptable
routes. The 105-design campaign found 13 correctness escapes after clean
emission, including BRAM, physical-input, SPI MISO, far-site state, and dense
state vehicles. Routing admission narrows uncertainty; it is not a silicon
certificate.

AGaMEMnon uses a three-tier model, and reports what it did.

## The three tiers

| tier | criterion | behaviour |
|---|---|---|
| 1 — **witnessed** | conduction evidence at this exact position: a vendor route that used the hop, a silicon sweep row, or a reviewed admission row | admit, silently |
| 2 — **encoding-certain** | no conduction witness here, but the selector codeword is certain | admit, and **record it in the build's confidence manifest** |
| 3 — **encoding-ambiguous** | the selector key conflicts across positions, or there is no clean-selector evidence at all | **refuse, always** |

Tier 3 is refused under *every* model, including for edges with perfect
conduction evidence. Knowing that copper joins A to B does not help if we would
program the mux to select C.

Likewise, tier 1 means the edge has a bounded witness, not that arbitrary
simultaneous use is qualified. The former 14-edge negative catalogue was
removed because all 14 edges conduct in isolated positive witnesses; the
original congested composition still failed. Never cite “tier 1” as proof of a
wide design.

### What makes a codeword "certain"

Exactly three bases, in order of preference:

* **`clean-physical`** — an exact, conflict-free observation of this very edge
  at this very position in `sel_edge_pairs.agdb`.
* **`unanimous-relative`** — a tile-relative key that *every* physical
  occurrence agrees on. One disagreement deletes the key permanently; the
  deleted keys are tier 3.
* **`byte-exact-closed-form`** — index arithmetic over the regular fabric that
  reproduces every physical observation of its class with zero counterexamples.
  Two forms qualify:

  | form | agreement with the shipped corpus |
  |---|---|
  | intra-tile connection box, `OMUX[3z+1] -> IMUX` | 65,902 / 65,902 exact |
  | switchbox entry, `RMUX <- OMUX` (same tile / one east) | 37,552 / 37,552 exact |

  A third closed form, used deep in bitgen's fallback chain for the intra-tile
  `IMUX <- RMUX` crossbar, scores 126,180 exact against **51 mismatches**. It is
  *not* admitted. That difference is why this is a measurement, re-run by
  `tests/test_routing_tiers.py` on every test run, rather than an assumption.

  **Measured 2026-08-20: the closed forms currently admit nothing the two
  observation tables do not already cover.** Every one of the 542 distinct
  intra-tile `OMUX[3z+1] -> IMUX` index pairs now has a unanimous relative key,
  and so does every surviving `RMUX <- OMUX` shape, so `tiered` and
  `tiered-tables` produce identical graphs. The forms are kept as a corpus
  cross-check and a safety net, not as a source of coverage; if you are looking
  for where the tiered model's extra edges come from, it is the relative keys.

A closed form is never applied to a relative key the corpus disagrees with
itself about: if the observations say the answer is position-dependent, a
position-independent formula cannot be the whole story for it.

## Choosing a model

```
agamemnon build design.v --uarch                    # tiered (default)
agamemnon build design.v --uarch --release-strict   # tier 1 only
agamemnon build design.v --uarch --research-unsafe --require-clean-selectors
                                                    # experimental features, clean selectors only
```

or, equivalently, `AGAMEMNON_ROUTING_ADMISSION=release-strict|tiered|tiered-tables`.
`tiered-tables` is the A/B control: tier 2 without the closed forms.

`--release-strict` is exactly the behaviour that shipped before this model
existed, byte-for-byte. Use it when every edge in the image must carry
conduction evidence — a qualification run, a silicon-claim artifact, anything
whose result will be quoted as evidence about the device. It is the tightest
selector gate, but the resulting whole image still needs its own observable
silicon contract before it becomes evidence.

`--require-clean-selectors` is an orthogonal fail-closed overlay. In particular,
it allows a research-policy build to instantiate an explicitly experimental
primitive while removing every edge that would need a conflicted, legacy, or
predicted selector encoding. The artifact remains research-policy and keeps its
sidecar; the overlay does not promote the primitive or turn a desk build into a
silicon claim.

Use the default for ordinary development. It routes more designs, and it tells
you precisely which edges it leaned on.

## The confidence manifest

Every tiered build writes `<output>.confidence.json` next to the bitstream and
prints a short summary. For each tier-2 edge the final route actually used it
records:

* the pip, its source and destination wires, and the tile whose configuration
  programs it;
* the selector basis, the emitted codeword, how many physical observations back
  that basis, and a sample of the positions they came from;
* the nets that used it;
* **the one row that would promote it to tier 1** — spelled as a row you can
  produce and paste, not as advice.

A build with no tier-2 edges says so explicitly: *release-strict clean*. That is
a stronger statement than a silent success, because it means the tiered graph
was available and the router did not need it.

```
[confidence] 6 of 412 routed edge(s) are tier-2 encoding-certain (exact codeword,
             no conduction witness at that position), touching 3 net(s)
[confidence]   X14Y9_RMUX13.X14Y10_RMUX49  (2 net(s), unanimous-relative)
[confidence]   ...
[confidence] manifest -> blinky.bin.confidence.json
[confidence] rebuild with --release-strict to refuse these edges instead of reporting them
```

The manifest is a work queue, not a permanent disclaimer. Evidence is cheap now
— the design-level witnessing rig runs hundreds of self-checking designs in
minutes — so tier-2 edges are expected to drain into tier 1 over time. Feeding
the `promotion_queue` array to that rig is the intended workflow.

## What the manifest does not claim

* It does not say a tier-2 edge conducts. It says the opposite: the codeword is
  exact and the electrical behaviour at that position is unverified.
* `agreeing_physical_observations: 1` and `: 158` are both "unanimous". The
  count is reported so you can tell them apart.
* The closed-form fan-in cross-check against the decoded tile template
  currently rejects nothing — the template's fan-in for RMUX and IMUX instances
  is complete — so a pass there is not independent confirmation.

## What this actually buys, measured

Measured 2026-08-20 on AGRV2KL48, comparing device graphs emitted from the same
chipdb under each model.

| | release-strict | tiered | research-unsafe |
|---|---|---|---|
| routing pips | 245,630 | **324,971** (+79,341, +32.3%) | 384,335 |
| wires with no way in | 22,527 | 22,167 | 22,125 |
| bel-input sinks with only one feed | 4,415 | 4,337 | — |
| bel-input sinks with six or more feeds | 6,665 | 8,450 | — |

Of the tier-2 edges, 54,944 are `clean-physical` — an exact conflict-free
observation of that very edge at that very position, so the codeword is not
extrapolated at all. The other 24,397 are `unanimous-relative`, backed by a
median of 86 agreeing physical observations; only 507 rest on a single one. The
manifest reports that count per edge so the difference is visible rather than
averaged away.

**And on routability, the honest answer is that it buys little.** Across 42
example designs built both ways: 32 routed under both models, 10 failed under
both, and there were **zero** conversions in either direction. Eleven of the 32
successful builds used tier-2 edges (61 of 528 routed pips in those builds), so
the router does take the new edges — it just did not need them to succeed
anywhere in this set. Fmax moved in both directions (−18 to +25 MHz over seven
comparable pairs) with no systematic effect; routing is not monotonic in these
knobs and none of that should be read as a timing benefit.

Every one of the ten shared failures is the same shape, and it is one this model
provably cannot address: an MCU-entry `BufMUX` that has **exactly one** downhill
pip in *all three* graphs — release-strict, tiered and research-unsafe alike.
Those entries are supplied by the MCU-edge corridor table, not enumerated in the
routing graph, so the missing alternates are absent from the topology rather than
refused by a gate. Widening admission cannot conjure an edge that no table
contains. That work belongs to the MCU-entry path model.

Where tiering does move the needle is reach: of the 70 wires audited as
targetable-but-unreachable under the strict gate, 6 are recovered by
`corpus_route` evidence promotion, **32 more by tiered
admission**, and 32 remain refused as tier 3 — all of them IO-ring wires whose
feeds have no clean-selector evidence at all.

## Related: load-time selector-injectivity guards

Admission decides which edges the router may use. A separate mechanism,
`agamemnon/engine/selector_injectivity.py`, checks that the selector tables
themselves are self-consistent -- that no physical mux is given two inputs with
one codeword, and that no table lists a source which the device graph shows is
not wired to that destination family. It runs at load and withdraws an
ambiguous codeword so the hop reports unmapped and bitgen fails closed.

The two mechanisms are complements, not alternatives: this document's tiers
decide whether an edge may be *routed*; those checks decide whether a codeword
may be *emitted*. They share an arbitration rule -- observation decides, and a
group nothing corroborates is refused whole.

## The boundary-terminal exception

The east/south MCU boundary muxes have a source-keyed *fallback* codeword table
used when no exact witnessed tuple exists. It lists **fourteen** sources, and
two of its `(lo, hi)` words are each claimed by two sources: `RMUX20`/`RMUX92`
share `(2,6)` and `RMUX49`/`RMUX25` share `(0,4)`.

What is established: the twelve sources that *do* have a witnessed exact tuple
use twelve distinct words, and the two extras — `RMUX25` and `RMUX92` — are
exactly the two entries with no witnessed row anywhere. So each collision pairs
a well-evidenced entry with an unevidenced one.

What is **not** established is that either entry is wrong. Reading the fan-in as
a flat twelve-input mux makes a fourteenth source impossible by pigeonhole, but
that reading is under active investigation: there is evidence of a further
selector position (index 8) that the reference backend programs alone for a *parked* or
constant-tied sink, while routed sinks get a `(lo,hi)` pair. If the real
encoding carries that extra dimension, two sources sharing a `(lo,hi)` need not
be a contradiction at all. **That table is owned elsewhere; this document owns
only the policy.**

The policy is the same under either reading, which is why it is safe to apply
now: the *guess* is withdrawn for the sources no observation supports, and every
witnessed tuple still resolves normally. Concretely, `RMUX25` and `RMUX92` lose
the fallback; `RMUX20` and `RMUX49` keep it. (Refusing all four would have been
the tidier rule and the wrong one — it breaks
`qualification/dual_carry3_routed.json`, which routes
`X14Y12_RMUX49 -> X13Y12_BBMUXE05` through a word twelve observations support.)
A colliding group with no witnessed member, or with two, is refused entirely,
because then nothing can arbitrate.

The refusal is enforced in both the device graph and the emitter, so the router
never spends a corridor on an entrance the emitter will reject. Its blast radius
today is zero — no observed RRG row into a BBMUXE uses `RMUX25` or `RMUX92`
without an exact tuple — which is what makes it worth having: it costs nothing
now and fires the day someone routes one.
