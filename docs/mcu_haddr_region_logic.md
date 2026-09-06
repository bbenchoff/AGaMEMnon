# High-address logic ingress

The original `mcu_haddr_region_logic_*` rows contain twelve vendor-derived consecutive
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

## HADDR18 alternative, September 6, 2026

Four additional normalized edges describe the HADDR18 path from
X13Y11_BufMUX08 through X13Y11_InputMUX08, X14Y11_RMUX69,
X14Y12_RMUX76 and X14Y12_IMUX02. InputMUX8 selects zero; its bit must be
cleared. The older InputMUX09 corridor remains available.

The exact vendor image SHA-256
`63f5afd304c5bd86a56690c54c77d3622da9623b48e485508383d2d8c7e23233`
passed three independent SRAM loads, each checking 32 reads of HADDR18 XOR
HADDR4 across all combinations of HADDR4/17/18/19 in forward and reverse
order. All 96 observations and both known-good controls passed. This
discriminates stuck outputs and substitution of HADDR17/19 for HADDR18.
The final reset succeeded and custody was released; no flash was written.
Firmware SHA-256:
`b9fbbe252a62b6e6c2e2b61ef93f6bd0962bc8c16ad9cdb2a9873bb884f9fdb5`.

This bounded source-specific conduction evidence admits InputMUX08 for this
root. It does not admit generic BufMUX/InputMUX interchangeability or establish
full-bus concurrency, timing closure, open-image equivalence or RAM correctness.
Raw vendor material and captures remain in AG32-Docs under
`tools/vendor_parity/gpt6_haddr18_conduction_20260906/`.

Fresh strict and tiered graph comparison adds exactly three PIPs and changes
or removes none. Removing the additions reproduces each preceding graph's
bytes and row order; all 808 edges touching protected output wires remain
unchanged. The graph identity pins reflect these measured additions and retain
the preceding exact snapshots for replay. HADDR18 now reaches a real slice
input in the strict graph. A complete audit of both address tables finds eight
other address lanes without logic reachability (15/16/20/22/23/26/27/28).
Full-bus capacity is still unproven.

## Remaining address paths

HADDR15/16/20/22/23/26/27 each passed three source-discriminating SRAM captures
of their exact vendor scout images: 672/672 full-word observations, with four
passing controls. HADDR28 separately passed 96/96 observations and two controls.
The target address bit and HADDR4 vary independently of two nearby address bits;
every word must equal their XOR. These are individual source-path witnesses,
not proof of concurrent bus capacity. Final resets completed, custody was
released, and neither flash nor images were modified.

The tables add 27 consecutive path rows and 25 unique configuration rows.
Shared path fields are deduplicated only when every encoding column agrees.
HADDR15/16/20 use the witnessed InputMUX05/06/10 alternatives; the other five
enter the routing mesh directly. The first-hop constraints admit only the
source-specific observed alternatives, preserving unrelated lane restrictions.

Private source artifacts and immutable captures remain in AG32-Docs under
`tools/vendor_parity/gpt6_haddr_matrix_conduction_20260906/` and
`tools/vendor_parity/gpt6_haddr28_conduction_20260906/`. The corresponding scout
extractions bind exact route/image identities to the normalized facts.
Fresh graph preservation, open-image behavior and general memory admission
remain separate obligations.

The combined graph adds exactly 18 PIPs over the pre-HADDR18 baseline in both
strict and tiered profiles. No prior rows change or disappear; removing the
additions restores the baseline byte-for-byte and all 808 protected-output
touching edges remain unchanged. All 64 address/data lanes now have individual
paths to real LUT inputs in the strict graph. This is static connectivity,
not a simultaneous allocation or timing result.
`qualification/mcu_address_ingress_silicon.json` publishes the exact image,
firmware and capture-log identities for all nine bounded source-path witnesses.
