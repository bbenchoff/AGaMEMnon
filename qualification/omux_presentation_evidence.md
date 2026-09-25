# OMUX(3z) presentation — evidence for `AGAMEMNON_OMUX_PRESENT0`

Status: **experimental**, opt-in, evidence tier `decoded` in the registry. The model below is
established from vendor images, and the wire this option drives is silicon-witnessed at every slice
where it is added. Images built with this option have not yet been witnessed on silicon.

## What the option does

Each logic slice `z` has three output wires, `OMUX[3z+0]`, `OMUX[3z+1]` and `OMUX[3z+2]`. The slice
BEL exposes only `OMUX[3z+2]` (F = Q). `OMUX[3z+1]` is reachable through the per-slice `OMUXFB` pip.
Nothing drives `OMUX[3z+0]`, so the router can never use a pip sourced there. The option adds one
`OMUXPRES` pip, `OMUX[3z+2] -> OMUX[3z+0]`, per logic slice listed in
`agamemnon/chipdb/omux3z_presentation_evidence.csv`. The seven MCU-edge sites keep their existing
`MCUEDGE` pip. A slice not listed keeps `OMUX[3z+0]` undriven, as before.

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

So for an F net the `OMUXPRES` pip costs no configuration bit: the LUT output is already on `+0`,
and bitgen leaves `CFG_OMUX<z>` bit 0 clear because `omux_output_sources()` binds the wire to F.
For a Q net, bitgen's existing same-tile `+2 -> +0` handler sets `CFG_OMUX<z>` selection 0, which
co-presents Q on `+2` and `+0` (the registered pattern). Bitgen needs no change.

This path differs from the `OMUXFB` bridge (`+2 -> +1`), which the uarch refuses to a combinational
driver (`combinational_copresentation`, X14Y4 excepted): the bridge's historical failure was bit 1
being SET for an F net, putting an undriven Q on `+1`. `OMUXPRES` never sets bit 0 for an F net,
and the uarch's bridge predicate matches only `+2 -> +1`, so `OMUXPRES` is unaffected by it.

## Per-slice silicon evidence (`omux3z_presentation_evidence.csv`)

One row per logic slice `(x, y, z)` whose `OMUX[3z+0]` wire has at least one silicon-witnessed
outgoing pip: the pip was used by a vendor-built image that passed its self-checking board test.
`witnessed_pips` counts those distinct outgoing pips. The table is the witness ledger of the
workbench pip-witnessing campaign, reduced to slices; it carries no path or image.

- 2,068 of the 2,112 logic slices are listed (132 LogicTILEs x 16), with 17,789 witnessed
  outgoing pips in total (1 to 11 per slice; median 9).
- 44 slices are unlisted: 40 in the right-edge column X20 (every X20 tile is missing 1 to 7) and
  4 at X12Y4. They get no `OMUXPRES` pip.
- All seven MCU-edge sites are listed; they keep their typed `MCUEDGE` pip instead.
- With the option on, 2,061 `OMUXPRES` pips are added (2,068 listed minus the 7 MCU-edge sites).

A witnessed outgoing pip proves the wire carried the slice output correctly on silicon under a
vendor configuration. It does not by itself witness an image built by this toolchain.

## What remains before it can be a default

- Silicon witness of images that route through `OMUXPRES` pips, for both F and Q nets.
- A claim review (evidence tier and approval) so it can run outside `research-unsafe`.
- Promotion of the physical graph identity (`special_routes.py` pinned counts); the option's
  graph profiles are registered in `agamemnon/engine/physical_graph_profiles.json`.
