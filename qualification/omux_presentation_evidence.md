# OMUX(3z) presentation — evidence for the default OMUXPRES pips

Status: **on by default** in every graph profile since 2026-09-24. `AGAMEMNON_NO_OMUX_PRESENT0=1` is
a surface-narrowing kill switch that restores the previous graph byte-for-byte (its profiles are
registered, and release-strict admits it the same way it admits `AGAMEMNON_NO_FFBRIDGE`).

## What the pips are

Each logic slice `z` has three output wires, `OMUX[3z+0]`, `OMUX[3z+1]` and `OMUX[3z+2]`. The slice
BEL exposes only `OMUX[3z+2]` (F = Q). `OMUX[3z+1]` is reachable through the per-slice `OMUXFB` pip.
Before this change nothing drove `OMUX[3z+0]`, so the router could never use a pip sourced there
(the inter-tile RMUX egress family, ~18.8k edges). The graph now has one `OMUXPRES` pip,
`OMUX[3z+2] -> OMUX[3z+0]`, per logic slice listed in
`agamemnon/chipdb/omux3z_presentation_evidence.csv`: **2,061 pips**. The seven MCU-edge sites keep
their typed `MCUEDGE` pip. Under a qualified BRAM TMUX09 source profile, `X14Y8_SLICE2` keeps the BRAM
feature's own measured-tree pip. A slice that is not listed keeps `OMUX[3z+0]` undriven.

## Why the pip is exact

`CFG_OMUX<z>` has three independent bits. **Bit k puts the slice's register output Q on `OMUX[3z+k]`.
With the bit clear, the wire carries the LUT output F.** This was decoded from vendor configuration
images:

- Registered drivers map wire index to bit index one to one.
- All combinational-driven nets read `000`, whichever wire they use.
- Vendor routes present combinational outputs on all three wires about evenly (655 / 632 / 651
  over 60 routed trees).
- Co-presentation (one slice output on two wires) appears only with registered drivers (514
  cases, zero combinational).

Silicon, same site, pip, sink and route at `X10Y3_SLICE6`, with a combinational driver on
`OMUX[3z+1]`: `CFG_OMUX6 = 010` is stuck low, `000` conducts 3/3.

For an F net the pip costs no configuration bit: the LUT output is already on `+0`, and bitgen
leaves `CFG_OMUX<z>` bit 0 clear because `omux_output_sources()` binds the wire to F. For a Q net,
bitgen's same-tile `+2 -> +0` handler sets `CFG_OMUX<z>` selection 0, which co-presents Q on `+2`
and `+0` (the registered pattern). Bitgen needed no change for this.

This path differs from the `OMUXFB` bridge (`+2 -> +1`). The uarch refuses that bridge to a
combinational driver (`combinational_copresentation`, X14Y4 excepted), because its historical failure
was bit 1 being set for an F net, which put an undriven Q on `+1`. `OMUXPRES` never sets bit 0 for an
F net, and the bridge predicate matches only `+2 -> +1`. `OMUX[3z+0]` fans out to neighbouring-tile
RMUX. The intra-tile crossbar is fed only from `OMUX[3z+1]`, so these pips do not replace the bridge
for reaching the crossbar.

## Evidence 1: per-slice vendor witnessing (`omux3z_presentation_evidence.csv`)

One row per logic slice `(x, y, z)` whose `OMUX[3z+0]` wire has at least one silicon-witnessed
outgoing pip: the pip was used by a vendor-built image that passed its self-checking board test.
`witnessed_pips` counts those distinct outgoing pips. The table is the workbench pip-witnessing
ledger reduced to slices; it carries no path or image.

- 2,068 of the 2,112 logic slices are listed (132 LogicTILEs x 16), with 17,789 witnessed
  outgoing pips in total (1 to 11 per slice; median 9).
- 44 slices are unlisted: 40 in the right-edge column X20 (every X20 tile is missing 1 to 7) and
  4 at X12Y4. They get no `OMUXPRES` pip.
- 2,061 pips = 2,068 listed minus the 7 MCU-edge sites.

## Evidence 2: silicon A/B of our own images (2026-09-24)

Twelve rando-corpus designs were built release-strict, seed 1, 10 MHz, each with the pips off and
on (on meant `experimental-strict` with the then-opt-in flag). Both arms were boarded with the
self-checking LED-rate harness (three runs, reset-held controls before and after). Results are in
the workbench, `tools/rando_corpus/results/omux_ab/`.

- **ON: 10 of 10 measurable designs PASS**, with edge counts identical to OFF: blinky, crc32_kat,
  sub32_kat, barrel32_kat, xorshift32_kat, bram_rom_kat, fsm_traffic, pwm_breathe, uart_tx_hello,
  shift_sevenseg. Together they route 381 OMUXPRES pips (2 to 79 per design): 185 on F-driven nets
  (bit 0 clear) and 196 on Q-driven nets (bit 0 set).
- serv_blinky was UNMEASURABLE in both arms, so it carries no signal either way.
- lfsr16x6_kat (OFF PASS) did not produce an ON image. Bitgen refused it, fail-closed, with one
  routed pip it could not encode: `X14Y8_OMUX08 -> X14Y8_OMUX06`, an OMUXPRES pip. The BRAM feature
  claimed that exact pair (`BRAM_FIXED_PRESENTATION`, its TMUX09 source-profile bridge) and returned
  "unencodable" outside the profile. It now defers the pair to the routing feature unless a TMUX09
  source profile is active, so the pip encodes like every other OMUXPRES pip.

## What remains

- Board the rebuilt default images, including lfsr16x6_kat and serv_blinky.
- `OMUX[3z+1]` as a sole presentation (instead of the bridge) is a separate model change.
