# RMUX30 left-pad selector disposition

Status: `already-release-covered-special-padfeed`

The L48 edge `X4Y4_RMUX20.X0Y4_RMUX30` is not a generic routing-selector
admission candidate. It is the qualified PIN_25 pad-feed edge and is owned by
the physical-I/O path.

`agamemnon/chipdb/padfeed_L48_left.csv` is the canonical emission record. Its
IOMUX0 row binds the routed `RMUX20 -> RMUX30` hop to the pad-tile companion
codeword `IOTILE(0,4) CFG_RMUX3[45,46]`. The routing feature recognizes that
exact physical edge before generic selector grouping, and the physical-I/O
feature emits the companion codeword when the left-pad output is selected.

This scope was already individually qualified before the later routing-wave
work:

- `qualification/left_edge_output_evidence.jsonl` trial
  `2026-07-15-l48-pin25-left-output` records the exact companion codeword and
  a passing PIN_25 silicon result.
- Trial `2026-07-15-l48-pin25-28-simultaneous` records the four left outputs
  routing and operating concurrently.

The matching row in `rrg_edges_full.csv` previously carried the generalized
destination-group label `CFG_RMUX5[1,8]`. That label did not describe the
cross-owned package encoding and is corrected to the canonical
`CFG_RMUX3[45,46]` value.

The edge intentionally remains absent from `sel_edge_pairs.agdb`. That table
stores generic destination-owned selector pairs and is admitted wholesale to
release-strict use. Adding this cross-owned edge there would both encode the
wrong owner and misrepresent a differential wave row as a new release
selector. Future differential-only routing waves require a separate row-tiered
experimental dataset and explicit `experimental-strict` selection; they must
not widen this generic release table.

This disposition changes metadata only. It does not change emitted bytes,
registry maturity, evidence tier, release permission, package scope, or the
existing fail-closed behavior.
