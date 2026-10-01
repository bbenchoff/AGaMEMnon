# Native clock-enable plus local Qin experiment

This composition is disabled by default for raw standalone use. It is enabled
only when both `AGRV2K_NATIVE_ENABLE_LOCAL_QIN=1` and
`AGRV2K_SHARED_CONTROL_ENABLE=1` are present. Each value is strict: it must
be `0` or `1`; an unset value means `0`. A value of `0` leaves DFFE local-Qin
lowering off. The ordinary CLI tries an optimized native candidate with
`AGRV2K_NATIVE_ENABLE_LOCAL_QIN=1` and compares it with a historical candidate
using `0`. The smaller completed mapping wins, with historical mapping winning
ties. Explicit overrides apply to both candidates.

The ordinary native-enable path remains responsible for accepting a positive-edge DFFE and lifting its `EN` net to the shared tile-control line.  The Qin pass considers only a mapped four-input LUT whose output drives one DFFE D input and whose inputs include that DFFE's own scalar Q bit.  The candidate DFFE must have scalar integer `CLK`, `EN`, `D`, and `Q` connections and no additional reset/control port.  It keeps its enable and group attributes.  A DFFE that does not form this own-Q loop, including one with constant D, is left unchanged by this optional pass.

For an eligible loop, the LUT input/INIT are permuted so own Q is on I[2], tagged as `LOCAL_QIN_I2`, and its packed slice has no F presentation of the old LUT result.  When the LUT output is externally observed, Qin retains it through a separate LUT copy.  Final packing must preserve both `LOCAL_QIN_I2` and `CLOCK_ENABLE_POS`, the enable group ID, the local `OMUX[3z+2] -> IMUX[4z+2]` route, and the shared-control selection.

The bounded r2 counted-load fixture was built twice from the same frozen source
and packing3 binary. Both runs used 72 generic slices and eight native-enable
slices in one preserved group. With local Qin off, those eight slices used
`LUT_COMPUTE_TO_FF`; with it on, all eight used `LOCAL_QIN_I2`. The direct
Python subprocess return code was zero for both runs.

The subsequent board batch ran the eight native-Qin state bits placed in tile
`X17Y10`, with local Qin off and on three times each, alongside the reference
and controls. The independently audited batch passed all candidate runs. This
is functional evidence for the counted load/advance/hold contract at that
composition. It does not establish a physical speed improvement, universal
gating, mixed-tile support, or general local-Qin timing/conduction behavior.

This switch does not widen the separate direct-D feedback pool.  Direct-D eligibility and its footprint restrictions remain on their existing path.
