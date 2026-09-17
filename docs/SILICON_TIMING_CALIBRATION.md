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
| LUT (A input) + IMUX entry, per stage | 0.436 ns | 0.608 + 0.336 = 0.944 ns | 0.46 |
| RMUX span, per pip | 0.305 ns | 0.418 ns (mean) | 0.73 |
| OMUX hop, per pip | 0.116 ns | 0.066 ns (mean) | 1.75 (weakly determined) |

Two consequences: the shipped model is ~1.6–1.7x pessimistic on whole paths, and — more important
for placement — its LUT:route **ratio** is wrong (logic overestimated ~2.2x, routing ~1.4x), so a
delay-driven placer using it under-weights routing hops by roughly 1.6x. LUT and IMUX cannot be
separated by I[0]-fed rings (one IMUX entry per stage); the split above scales both equally.
Measurement tooling, raw results and the fit live in the workbench repository
(`tools/vendor_parity/timing_ro_20260916`).

## The hook

```
AGRV2K_TIMING_CAL="RMUX=0.73,IMUX=0.46,OMUX=1.75,LUT=0.46"
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

- Per-tile speed map (full 132-tile sweep) and the LUT/IMUX split via I[3]-fed rings.
- A/B of `placer_heap` on devdb vs calibrated delays on SERV, judged under one external STA and
  then on silicon Fmax, before any default changes.
