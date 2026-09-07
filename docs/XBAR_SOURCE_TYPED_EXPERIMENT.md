# Source-typed crossbar experiment

`AGRV2K_SOURCE_TYPED_XBAR=1` enables an unqualified native placement experiment.
It is off by default. It is not a release qualification or a replacement for
the negative-image registry.

The native producer marks ordinary slice cells with
`AGRV2K_SOURCE_TYPED_XBAR="1"`. The emitter resolves each marked lane-1 route
back to the actual F or Q driver: F clears `CFG_OMUX[z][1]`, Q sets it. A route
without the matching source driver or competing F/Q demands on the same lane
is refused. The marker persists in the routed checkpoint; repacking does not
depend on the process environment. Unmarked historical checkpoints preserve
their previous emission behavior.

The native experiment permits odd ordinary slices and permits the source
cell's combinational presentation bridge only with this typed model. It does
not add graph edges, alter endpoint/control/clock restrictions, remove fences,
or update any chipdb or retained-image hash. Explicit route-through cells keep
their separately characterized handling and are not marked by this experiment.

The supporting vendor comparison covers 1,211 direct arcs and all 240
cross-slice pairs. Destination selectors match throughout. Source mode is
essential: vendor lane 1 can carry Q or LutOut. The comparison includes 953
Q-source arcs, 251 explicit LUT-source arcs and seven arcs from two implicit
identity route-throughs. Source-aware routing preparation matches the tested
vendor selector and presentation bits; this is not whole-image equivalence or
open-tool silicon qualification.

Promotion still requires byte-identical retained images, fresh-source width
builds and density/routing comparisons, and control-first silicon qualification.
The default parity policy remains in place until those gates decide the change.
