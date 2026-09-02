# Silicon evidence for the evidence-tier model at the MCU boundary

## Summary

The tiered routing graph distinguishes **tier 1** ("witnessed" — conduction evidence at this exact
position) from **tier 2** ("encoding-certain" — the selector codeword is exact, but nothing proves
the wire conducts *here*). `--release-strict` refuses tier 2. Until now that refusal rested on a
conservative argument rather than on measurement.

On 2026-09-02 it was measured. Thirty-six MCU-boundary read lanes were observed on silicon across
six independently routed images, each lane carrying a value known independently of the design under
test — hard constants, combinational address echoes, and a free-running counter:

```
driver chain uses >= 1 tier-2 pip : 14 delivered, 13 FAILED
driver chain is tier-1 only       : 12 delivered,  0 FAILED
```

- **No tier-1-only boundary chain failed** (0 of 12).
- **Every failure — 13 of 13 — rode a chain containing at least one tier-2 pip.**
- Tier-2 use is therefore **necessary but not sufficient** for failure. 14 tier-2 chains delivered
  anyway, so a tier-2 edge is close to a coin flip at the boundary (48% failure), **not** a dead
  edge.

Every failing build would have been refused by `--release-strict`.

## Why this matters more than the numbers suggest

**The failure mode is silent.** An undriven MCU read bit returns `1`. A read lane whose chain does
not conduct therefore returns a perfectly plausible value, and a design whose logic is entirely
correct can produce a deterministic, repeatable, wrong answer that looks exactly like a
correctness defect in the engine.

That trap was walked into and then diagnosed in the same session. A bounded A/B vehicle produced
deterministic silent-wrong output on both arms; the cause turned out to be its own read-lane
routing, not the feature under test. It had every appearance of a genuine escape.

**Practical rule:** do not attribute a silicon miscompare to the engine, and do not record a
silicon-witnessed result, from a build that is not release-strict clean at the MCU boundary.


## The sharpest single test

The clearest form of the result came from rebuilding one bounded vehicle — a positive-edge,
active-high synchronous clear-to-zero register read out over the MCU boundary — with
`--release-strict`.

Under release-strict the tier-1 graph is sparser, so the router took **seven hops** to reach all
three of the vehicle's read lanes. Seven hops is the length at which tier-2 chains failed 10 times
out of 15 in the same session. All three tier-1 lanes delivered, and the register's full functional
contract passed 3 of 3 deterministic repetitions with a validated vehicle (stimulus echo exact,
constant canary clean):

```
init-clear -> q=0 ;  set -> q=1 ;  clear -> q=0 ;  re-arm -> q=1 ;
both asserted -> clear wins ;  alternating set/clear -> 0x5555
```

Same RTL, same lowering, same BEL as an experimental-strict build of the same design that had
failed every check. The difference was admission, not logic.

## What is deliberately NOT concluded

- **No edge is blacklisted.** Tier-2 edges are not dead: 14 of 27 delivered. Blacklisting on this
  evidence would repeat the mistake the 2026-08-13 conduction reframe already retired once, where
  congestion artifacts were misread as per-edge silicon death.
- **No claim about tier 2 inside the fabric.** The sample is MCU-boundary read lanes only.
- **No hop-count or fan-out rule.** Both were proposed during the same session and both were
  falsified:
  - *hop count*: 22/22 lanes at ≤5 hops delivered and 13/18 at ≥7 failed, until a preregistered
    prediction was refuted by a 7-hop lane that tracked its input exactly.
  - *driver fan-out*: a controlled A/B did show that splitting a shared constant across separate
    physical constant LUTs improves delivery from 2/7 to 5/7 — so fan-out matters — but it cannot
    be the mechanism, because the known-good `public32` control drives ten boundary lanes from one
    constant LUT over 8-to-12-hop chains and delivers all ten.

  Long chains and high fan-out remain useful *correlates*: they are what push the router onto
  tier-2 edges in the first place.

## The tier-1 arm, at scale

`public32` is the control that runs at the head of every board session. It is composed by
`qualification/compose_mcu_ahb_public32_exact_map.py`, which uses only the strict graph of the
`public16` composer plus an explicitly reviewed branch list — a hand-composed exact map of reviewed
routes rather than a router result.

Its `$PACKER_GND_NET` drives ten `MCU_DOUT` lanes (`h19, h20, h21, h23, h25, h26, h27, h28, h29,
h31`) from a single `X14Y11_OMUX14` over chains of 8, 9, 11 and 12 hops. Every one of those lane
indices is a bit that must read `0` in the checked identity word `0x4147414d`; the oracle checks
that word 64 times and additionally requires `word[1] == word[2] == word[3] == 0`. Since an
undriven lane reads `1`, one non-delivering lane would fail the control — and it does not fail.

So long, high-fan-out, OMUX-driven boundary chains **do** work on this silicon when the routes are
reviewed. `public32` is the tier-1 arm of the same experiment, and it agrees with the pooled table.

## Where this shows up in the tool

`agamemnon/engine/routing_tiers.py` carries the measurement in
`BOUNDARY_TIER2_SILICON_EVIDENCE`; it is appended to the confidence manifest's verdict and printed
in the build's `[confidence]` block whenever a build is not release-strict clean. Nothing about
emission or admission changed — the engine now simply states what the unknown was measured to be.

## Method

SRAM-only, control-first, one board session per image group, with a passing known-good `public32`
at the head of every session. All observations deterministic across repetitions. Zero flash writes,
zero power-on resets, zero rewires, zero option-byte writes; final reset issued and the board lock
released each time.

Device `AGRV2KL48`. The per-lane data, the chain reconstruction from each build's own routed
netlist, and each build's tier-2 set taken from its own confidence manifest are retained in the
reverse-engineering workbench alongside the raw board logs.
