# The “does-everything” roadmap

This document defines the distance between today's fail-closed subset and a
completely open, broadly vendor-capable AG32 toolchain. It is a goal map, not a
support claim. Current state is authoritative in [STATUS.md](STATUS.md) and the
near-term order is in [ROADMAP.md](../ROADMAP.md).

The phrase “full vendor parity” is intentionally avoided as a current metric.
The 2026-08-24 campaign classified 105 hand-authored designs but had no sealed
holdout. It found 25 narrow parity successes, 52 routability gaps, and 13
correctness escapes. That evidence is strong enough to guide work and too small
and selected to estimate arbitrary-design success.

## What “does everything” would require

A complete result must satisfy all of these independently:

1. **Open representation:** every emitted configuration field has a public
   meaning, provenance, and open encoder; no closed executable or copied design
   image is required.
2. **Architecture coverage:** all usable logic, routing, clock, memory, IO,
   hard-block, MCU-boundary, and package resources are represented.
3. **Robust implementation:** ordinary and structural RTL place and route over
   realistic widths/utilization without per-design route patches.
4. **Logical correctness:** synthesis, packing, timing semantics, and routed
   evaluation agree with independent models across a broad generated suite.
5. **Physical correctness:** exact board contracts pass across modes, clocks,
   placement regions, PVT, simultaneous use, and supported packages.
6. **Fail-closed completeness:** unsupported or known-wrong surfaces are
   identified before an image is emitted, rather than by silent target failure.
7. **Deployment completeness:** reproducible releases, safe programming and
   recovery, stable APIs, documentation, and hardware fixtures exist.

No one item substitutes for another. In particular, byte-exact encoding and a
correct routed Boolean model do not imply physical correctness; the campaign's
BRAM, input, MISO, clock-reach, and density escapes demonstrate that gap.

## Configuration surface

The image has three useful conceptual planes:

| Plane | Current state | Completion condition |
|---|---|---|
| Global/configuration-chain preamble | Openly generated; exact retained profiles and a bounded HSE=8 silicon frequency surface | All sources, outputs, modes, and reset/clock semantics decoded and qualified |
| Design-neutral fabric body | Generated from open code/data, byte-exact to the decoded reference body, accepted by L48 FCB | Functions of remaining reserved/unnamed fields explained; behavior qualified beyond acceptance |
| Design overlays: cells/routes/hard blocks | Partial, evidence-tiered, strict conflict rejection | Every supported resource/mode encoded from public data with complete semantic and physical evidence |

The old “copy the canvas” blocker is closed: the base is generated. The new
frontier is naming and qualifying what designs put on that base.

## Routing and placement

### Already established

- a large exact physical and unanimous-relative selector corpus;
- zero-counterexample closed forms for bounded regular classes;
- conflict preservation and strict refusal;
- all 14 edges in the invalid historical negative catalogue conduct in bounded
  positive witnesses;
- exact small and peripheral compositions across much of the L48 fabric.

### Still required

- honest whole-device topology/selector coverage metrics, distinct from an
  observed-corpus denominator;
- special-block, pad, MCU-exit, BRAM, and clock feeder completion;
- deterministic wide placement and negotiated routing;
- user/structural feasibility convergence where semantics are equivalent;
- congestion/density rules validated on silicon rather than inferred from
  individual edges;
- scalable timing with clock skew, IO, BRAM, PLL, package, and PVT models.

The campaign's 52 routability gaps are the current benchmark pool. A general
algorithmic improvement must move a family without adding a route pin or
weakening selector policy.

## Logic, state, and correctness

Small Boolean, shift, arithmetic, LFSR, fanout, counter, and AHB vehicles prove
useful exact points. Open defects `VP-AGM-001` and `003`–`005` show that
feedback, next-state, rotate/reset, and add/reset compositions remain unsafe to
generalize. `VP-AGM-009` shows that a 13%-register, 7–8%-LUT user design can
match the routed evaluator and still diverge on silicon.

Completion requires:

- minimized triggers and fail-closed guards for every escape family;
- generalized repairs that pass the original preregistered contracts;
- broad metamorphic/generated model suites;
- density, placement-region, reset, clock-enable, and simultaneous-net
  coverage;
- a sealed holdout created only after architecture and admission rules freeze.

## MCU/fabric boundary

The exact public32 map, retained narrower banks, constant endpoints, status
overlays, and local-interrupt composition establish a strong but narrow slave
boundary. The wide frontier remains:

- fresh `regbank16` no-image;
- placement divergence in `addsub16`;
- generic application-owned state and overlays;
- complete AHB request/control semantics, alternate clocks/resets, wider
  address decode, bursts, and error behavior;
- AHB master and DMA.

The exact public32 composer reproduces its existing reviewed artifact by
replaying and validating the reviewed branch; no reviewed hash moved. A future
different candidate must be semantically reviewed and requalified, never
simply repinned.

## BRAM, PLL, clocks, and carry

### BRAM

Retained exact X13Y4 corridors and profiles are not a general BRAM model.
`VP-AGM-006` proves that currently modeled INIT/config equality can coexist with
zero reads on alternate x1/x18 compositions. Completion needs the missing
static/read field or physical-path explanation, then systematic sites, widths,
ports, clocks, outputs, writes, mixed modes, collisions, and inference.

### PLL and clocks

Bounded divider/output-frequency evidence is strong for HSE=8. `VP-AGM-007`
shows that far-site state delivery is not thereby qualified. Completion needs
clock networks/regions/seams, gating/reset, alternate outputs and HSEs,
phase/duty/feedback/bypass, and placement-aware physical validation.

### Carry

Same-tile, one X20 corridor, and one seam are exact points. Completion needs
all columns/seams, multiple simultaneous chains, density, branching policy,
timing, and fallback equivalence.

## IO and peripherals

Exact L48 outputs, bounded OE, UART0/1/2 TX, SPI0/1 TX, and I²C0/1 active
open-drain transactions are the current positive boundary. `VP-AGM-008`
captures the counterexample: exact-looking PIN_10/PIN_12 ingress and SPI0/SPI1
MISO compositions can be physically stuck.

Completion requires:

- generic physical ingress and bidirectional IO across every supported pin;
- electrical modes, voltage banks, drive/slew/pulls/Schmitt, simultaneous IO,
  PVT, and signal integrity;
- UART RX and full controller-mode breadth;
- repaired SPI MISO, then duplex, modes, dual/quad, DMA/interrupt, and timing;
- broad I²C transfers, stretching, addressing, arbitration, simultaneous
  controllers, electrical margins, and DMA/interrupt;
- timers, CAN with a transceiver, USB device/host/OTG, Ethernet with a PHY,
  external ADC/DAC/comparator fixtures, RTC clocking, and peripheral DMA;
- independent board qualification for L64, Q32, L100, and AG32VH/PSRAM parts.

## CPU-scale and real workloads

The retained SERV route is an exact replay, not broad CPU proof. A fresh SERV
build/simulation result is lower-tier evidence until the image passes a complete
board contract. CPU-scale completion needs:

- repeatable fresh placement/routing without route pins;
- directly observed register-file writes and BRAM semantics;
- broad instruction, branch, load/store, exception, CSR, interrupt, and trap
  coverage;
- several unrelated applications and generated workloads;
- a sealed, independently scored holdout.

Results must be reported separately as build success, logical/model success,
physical success, and vendor comparison.

## Toolchain and release system

A complete technical backend still needs a usable product boundary:

- reproducible Windows/Linux/macOS installation and pinned tool bundles;
- deterministic database generation and reviewed cache/artifact updates;
- fast, diagnostic placer/router failure reports;
- safe DAP/USB/UART programming, backup, verify, and recovery;
- append-only normalized evidence and automated fixture control;
- stable project, SDK, and primitive APIs;
- documentation whose support statements are generated from or checked
  against the same evidence manifests.

## Ranked next actions

1. Explain `VP-AGM-006` through `009` and add generalized refusal/repair rules.
2. Improve wide placement/routing on `regbank16`, `addsub16`, and the 256-bit
   pair without per-design exceptions.
3. Repair and requalify physical ingress/SPI MISO before adding RX breadth.
4. Establish automated hardware-in-the-loop coverage, then freeze rules and
   create a sealed holdout.

The finish line is not “a large database” or “one impressive demo.” It is an
open toolchain that can state, test, and enforce the difference between what it
knows how to encode and what it has proved will work.
