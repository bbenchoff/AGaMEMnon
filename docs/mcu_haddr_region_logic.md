# High-address logic ingress

The `mcu_haddr_region_logic_*` tables contain twelve vendor-derived consecutive
route edges and exact destination codewords from one simultaneous HADDR[4,29,30,31]
logic probe. They are normalized observations, not raw vendor artifacts or a
silicon qualification. The probe implements `(HADDR[31:29] == 3'b011) ^ HADDR[4]`.

Source identities: vendor image SHA-256
`bd372a8f05a9adc33f1cc701bfe846b070491678d3eb3d8f5c19b128e0e5d9fb`;
route SHA-256 `6451208e24d3f55d963b1e307f7725880724facc668f02bb7d78293dd4c2b982`.
The private source artifacts stay outside this repository. Evidence label:
`vendor-derived-haddr-region-20260905`.

Each lane has three consecutive edges to a distinct input of the X14Y10 LUT.
Fabric selectors replace their complete two-hot fields. HADDR30's MCU
InputMUX1 selector is a one-bit zero; HADDR31's InputMUX0 selector is a one-bit
one. A zero selection must clear the field, not be treated as absent metadata.
No LUT cell arc is promoted as a free routing edge.

Five of these edges were absent from the ordinary graph. Clean baseline and
candidate emissions in both release-strict and tiered physical profiles show
exactly five additions, no removed or altered rows, and no change to any edge
touching the protected left-output catalog wires. Removing the additions
reproduces each prior graph byte-for-byte. This supports updating the graph
identity pins, not any broader conduction or timing claim. Ordinary graph
generation uses the existing wire-delay model; the observations supply no new
measured delays.

Retained-image compatibility, fresh source builds, and silicon qualification
are separate gates. These tables do not authorize initialized writable memory
or relax its existing admission rules.
