# Native-enable packing audit

`tools/analyze_native_enable_packing.py <placed.json> --pretty` audits the
JSON written by an enabled `nextpnr --write` run. It is read-only and reports:

- native FF count per enable net and the required `ceil(FFs / 16)` line-0 roots;
- each group’s actual tile distribution;
- spare slice capacity occupied by combinational slices; and
- violations of the current isolated-tile contract.

The current implementation already coalesces each same-net group into chunks
of at most sixteen and assigns one `CLKEN0` root per chunk. It also permits
`FF_USED=0` combinational slices in those tiles. A group therefore fragments
only when it exceeds sixteen, has fixed/region constraints that make one tile
impossible, or fails placement; it is not split because the packer treats its
members as unrelated.

The binding restriction is sequential: a native-enable tile may not contain an
ordinary FF or an FF using a different enable. This is an observed silicon
boundary. The audit treats a mixed tile as an error even when it would reduce
the number of occupied tiles.

## Shared data-LUT packing experiment

`AGRV2K_LUT_FF_BROADCAST=1` enables a bounded packing transformation. When
one unconstrained LUT feeds only the D pins of multiple packable registers,
the packer duplicates the function and fuses each copy into its consuming
register's slice. N registers plus one shared LUT become N fused slices.
The option defaults off; `0` explicitly disables it and other values fail.

The transformation excludes own-Q feedback, externally observed data outputs,
fixed or region-constrained cells, constrained/routed data nets and preserved
cells. Existing LUT/FF fusion, control isolation and routing legality still
apply. It does not admit ordinary FFs into native-enabled tiles or alter the
native control line.

An ordinary-source regbank16 A/B retained 32 native registers while reducing
87 slices in 18 tiles to 71 slices in 17 tiles. Model Fmax decreased from
181.46 to 153.40 MHz. The separate data-logic build used 68 slices, so this
does not establish an overall area or speed advantage over that alternative.
These new images have not been qualified on silicon.

The audit checks placement and isolation, including missing placements and
different enable groups sharing a tile. It cannot establish selector behavior,
readback correctness, source equivalence, or silicon capacity. Selection of a
supported default requires ordinary-source regression and physical qualification
of the resulting composition, in addition to retained-image reproduction.
