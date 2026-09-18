# Silicon timing calibration

Status: **default since 2026-09-17** (see "Promoted to default" below); previously opt-in. This documents the `AGRV2K_TIMING_CAL`
hook in the `agrv2k` uarch and the silicon measurement behind its suggested values. It is not
timing sign-off and does not change any qualified checkpoint.

## What the shipped timing numbers are

- Per-pip interconnect delay is the `delay_ns` column of the devdb `dev_pips.csv` (a vendor-STA
  fit; 0.05 ns when blank). The uarch reports it through `getPipDelay` and folds it into the
  Dijkstra `estimateDelay` lookahead used by router2 and the analytic (`placer_heap`) placer.
- Cell delays are the decoded vendor library constants in `agrv2k.cc` (`SLICE_LUT_TO_F_NS`
  A/B/C/D = 0.608/0.565/0.474/0.149 ns, setup, clk->Q 0.312 ns, carry arcs).
- The constructive `pack_condplace` placer (the default for small designs) is adjacency-driven and
  does not consume delays; `placer_heap` (used first for dense/MCU-boundary designs) and router2 do.

## What silicon says (2026-09-16)

Ring oscillators of explicit kept LUT4 stages, BEL-pinned one tile at a time, were built by this
flow (release-strict, `--ignore-loops`), loaded over SWD, and their frequency measured by an
external hardware edge counter. Fitting half-period = N·t_fixed + n_RMUX·t_RMUX + n_OMUX·t_OMUX
over the retained routed netlists (per-family pip counts) gives, on the pilot set:

| term | silicon | shipped model | ratio |
|---|---|---|---|
| LUT (A input) + IMUX entry, per stage | 0.529 ns | 0.608 + 0.336 = 0.944 ns | 0.56 |
| RMUX span, per pip | 0.280 ns | 0.418 ns (mean) | 0.67 |
| OMUX hop, per pip | 0.030 ns | 0.066 ns (mean) | ~0.5 (weakly determined) |

(129 rings, all 128 buildable logic tiles plus a 31-stage reference; RMS 0.72 ns on 14–30 ns
half-periods. The 6-ring pilot fit predicted the other 123 tiles to +1.0% mean / 3.6% sd before
refitting, so the model generalizes across the array. Tile-to-tile residual sd is 0.055 ns per
stage, ~10%, with column X12 slowest and X9/X3 fastest.)

Two consequences: the shipped model is ~1.5–1.8x pessimistic on whole paths (logic ~1.8x, routing
~1.5x), and its LUT:route **ratio** is off by ~1.2x in the direction of under-weighting routing
hops. Per-family constants fit silicon better than per-pip devdb values scaled by family (RMS 0.72
vs 0.81 ns): the devdb's within-family per-pip variation is not something silicon agrees with.
Rings fed on I[3] (the D input) on seven of the same tiles separate LUT from IMUX: the A input
costs +0.268 ns more than D per level (sd 0.056; vendor constants say +0.459), giving LUT ≈ 0.59×
and IMUX ≈ 0.56× of the vendor numbers, with the vendor's ~4× A:D ratio holding on silicon. LUT
input-pin assignment is therefore a real ~0.27 ns-per-level lever for critical paths.
Measurement tooling, raw results and the fit live in the workbench repository
(`tools/vendor_parity/timing_ro_20260916`).

## The hook

```
AGRV2K_TIMING_CAL="RMUX=0.727,IMUX=0.56,LUT=0.59,OMUX=0.55"
```

Each `FAMILY=scale` multiplies the devdb `delay_ns` of every pip whose **destination wire name
contains** that token (RMUX, IMUX, OMUX, BufMUX, InputMUX, CtrlMUX, SeamMUX ...); `LUT=` scales the
`SLICE_LUT_TO_F_NS` cell arcs. Unlisted families are unscaled; unset = vendor numbers, byte-for-byte
the previous behaviour. Scales must be > 0; a malformed item is a hard error. The uarch logs
`silicon timing calibration active (...)` when it is on.

It only changes what the placer/router/STA *believe*; it does not change legality, the strict
routing graph, or bitstream emission. Because router2 is delay-driven, a calibrated build can route
nets differently from an uncalibrated one — treat calibrated images as fresh research builds.

## Open

- A flat per-family override syntax so the hook can express the better-fitting constant-per-family
  model exactly; a LUT input-pin permutation pass for critical paths.
- A/B of `placer_heap` on devdb vs calibrated delays on SERV, judged under one external STA and
  then on silicon Fmax, before any default changes.

## Companion: `AGRV2K_MIN_INPUT_INDEG` (placement legality, opt-in)

Dense designs exposed a second gap while running the A/B: HeAP may park a consumer on a slice input
whose wire has only one or two admitted feeding pips (70 of 8,448 inputs have a single feed, 234 have
at most two; the worst sit in the X1 and X20 columns), and router2 then loses exactly that last arc
under congestion. `AGRV2K_MIN_INPUT_INDEG=N` (default 1 = the existing "has any ingress" fact) makes
`isBelLocationValid` require at least N feeding pips on every connected data input of a *movable*
slice; hard-packed cells keep the N=1 rule. N=4–5 excludes ≤ 6 % of input pins and turned a
1,178-slice SERV that failed 17/17 seeds into a routable one. Research-only until the placement
policy change is promoted with silicon evidence.

## Design-level silicon results (2026-09-17)

A SERV core (servile, register file stubbed to zero, 143 slices, HeAP placement from the ordinary
`build --uarch --release-strict` path) was re-packed at each qualified PLL rate and run on the board
with its LED rate checked against the fixed cycles-per-instruction invariant:

| | MHz |
|---|---|
| silicon | PASS at 96, FAIL at 110 |
| nextpnr STA, shipped devdb model (build log) | 59.7 |
| external STA, shipped model (`sta_routed.py --model devdb`) | 76.0 |
| external STA, calibrated model (`--model cal`) | 114.3 |

So the shipped model is 1.6–1.8× pessimistic on a real design, and the ring-derived calibration is
~10 % optimistic at design level (clock skew, pad paths and the scaled setup constants are not
measured by rings). For `--freq` closure a derated calibration (≈ 0.85 × the calibrated Fmax) is the
safe form; for placement only the ratios matter.

**Caveat for fresh sequential builds (open defect, see the workbench BLOCKERS):** a pad input that
fans out directly into slices using the internal Qin feedback (`AGRV2K_REGISTER_INPUT_MODE=
LOCAL_QIN_I2`) misbehaves on silicon although every routed-netlist simulation is correct. Register
such inputs once inside the fabric (`rst_r <= reset`). The numbers above were taken with that
workaround.

## Promoted to default (2026-09-17)

`build --uarch` now sets, unless the user's environment overrides them:

```
AGRV2K_TIMING_CAL=RMUX=0.855,IMUX=0.66,LUT=0.69,OMUX=0.65   # calibrated ratios, derated x0.85 for closure
AGRV2K_MIN_INPUT_INDEG=5                                      # placement legality floor (routability)
```

Evidence (same netlist, same seed budget, HeAP at a 40 MHz target, highest passing PLL rate on the
board measured with the LED-rate invariant, `tools/vendor_parity/timing_ro_20260916/serv_ff/fmax`):

| design | devdb-delay placement | calibrated-delay placement |
|---|---|---|
| SERV core, 143 slices (3 seeds each) | 110 / 120 / 120 MHz | 133 / 110 / 133 MHz |
| SERV + FF register file, 1,178 slices (56 %) | 80 / 72 (+ 72 / 80 at the 10 MHz target) | 64 / 96 / 72 / 90 / 64 MHz |

The calibrated-delay placement holds the best result on both designs (133 vs 120, 96 vs 80), its
mean is higher on the core and level on the dense design, and on the dense design it routed more
seeds. The derate keeps `--freq` closure safe: the undated calibrated STA was +10 % optimistic on the
core and −30 % conservative on the dense design; ×0.85 brackets both.

The defaults act through the uarch's `AGRV2K_TIMING_CAL` and `AGRV2K_MIN_INPUT_INDEG` hooks, so
they take effect only with a nextpnr built from this revision of `agrv2k.cc` (older binaries
ignore the variables and behave as before). `AGRV2K_REACH_EXACT=1` (cap-free reach legality) is
compiled but not yet exercised on a design and stays opt-in.

## Input-ingress family rule and control-sharing clock gate (2026-09-17, evening)

Two defects found while measuring the open flow against the vendor flow on the same RTL (a 32-bit
LFSR + 32-bit accumulator probe; AG32-Docs `tools/vendor_parity/timing_ro_20260916/vendor_cmp/RESULTS_20260917.md`):

- **Slice inputs fed only by same-tile OMUX wires.** In the tiered (plain `build --uarch`) admission
  graph nine slice `I[0]` pins have feeders, but every feeder is an OMUX wire of the same tile, so no
  externally driven net can reach them (`X20Y10_IMUX56`, `X20Y11_IMUX56`, ...). `AGRV2K_MIN_INPUT_INDEG`
  counts feeders without regard to family, so an ordinary LUT with an external net could be parked
  on such a pin and lose its arc in routing. `slice_data_inputs_have_ingress` now also requires, for a
  free (non-cluster) movable cell, at least one non-OMUX feeder on every connected input. Dedicated-carry
  cluster members keep the count rule: their `I[0]` carries the slice's own Q feedback, which those OMUX
  feeders exist for. Test: `tests/test_agrv2k_external_ingress.py`.
- **Control-sharing candidates on non-bus clocks.** After a successful isolated baseline the CLI
  measures the experimental "mixed"/"dual" register-sharing profiles. Both put a native consumer on
  local clock line 1, which bitgen accepts only under the qualified MCU-bus GCLK0 profile
  (`features/clocks.py`). On a PLL-clocked design the candidate could route and then abort the whole
  build in bitgen, depending on placement luck. The opportunity scan now offers no sharing profile unless
  the baseline routes an `MCU_BUS_CLOCK` cell, and any `SystemExit` inside a candidate build rejects
  the candidate instead of the build. Test: `tests/test_control_sharing_clock_gate.py`.

The accumulator measurement uses a register fused into each carry slice: SUM
drives the flip-flop's D directly. Its accumulator has no synchronous reset;
reset instead clears the LFSR and gates the addend. That holds the accumulator
while reset is asserted and is not equivalent to clearing its value. The
checker solves its initial state. The corrected 33-site corridor runs
X20Y12 -> X20Y11 -> X20Y10_SLICE0. Some A pins admit only local own-Q feedback;
the [local-input packer](CARRY_LOCAL_INPUTS.md) places live addends on B and
removes the routed D/VCC ingress demand for eligible registered chains.
