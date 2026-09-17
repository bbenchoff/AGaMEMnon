# Silicon timing calibration (experimental, opt-in)

Status: **research**. Default builds are unchanged. This documents the `AGRV2K_TIMING_CAL`
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
LUT and IMUX cannot be separated by I[0]-fed rings (one IMUX entry per stage); the split above
scales both equally.
Measurement tooling, raw results and the fit live in the workbench repository
(`tools/vendor_parity/timing_ro_20260916`).

## The hook

```
AGRV2K_TIMING_CAL="RMUX=0.727,IMUX=0.474,LUT=0.474,OMUX=0.55"
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

- The LUT/IMUX split via I[3]-fed rings; a flat per-family override syntax so the hook can express
  the better-fitting constant-per-family model exactly.
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
