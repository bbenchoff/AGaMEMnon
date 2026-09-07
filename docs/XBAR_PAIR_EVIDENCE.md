# Even-slot claim: evidence correction, 2026-09-06

The parity placement policy is retained, but its claim of guaranteed conduction
is disputed. This correction changes no placement, routing, encoding or graph
admission behavior. It does not qualify odd slices or withdraw any negative.

The historical 80-row counter sweep contains 74 passing and six failing trial
outcomes. However, all 80 recorded `OMUX->IMUX` pips are same-slice feedback:
`OMUX_index // 3 == IMUX_index // 4`. They are not the distinct-slice links
identified by the row's `zs,zd` fields. The producer selected the first matching
pip in any net rather than authenticating the intended data connection.

The later corrected pip sweep contains 21 rows: 11 have a physical pip and ten
have none. All 11 nonempty pip records have the reverse direction from their
declared slice pair. For example, the `(0,2)` row records `OMUX07.IMUX00`, which
is slice 2 to slice 0. Do not silently transpose all rows: missing physical
routes and experiment-specific connectivity still require resolution.

Two saved final counter routes independently demonstrate the attribution issue:

| Saved route | Actual data dependency | Direct cross-slice OMUX-to-IMUX pip |
|---|---|---|
| `cnt2_routed.json` | slice 15 Q to slice 4 LUT input | None; uses an RMUX mesh path |
| `cnt2p_routed.json` | slice 7 Q to slice 1 LUT input | None; uses an RMUX mesh path |

These saved routes do not authenticate every historical trial or explain each
failure. They establish that a passing placement trial is not necessarily a
direct crossbar witness. The six failed trial labels remain `(0,1)`, `(0,5)`,
`(1,0)`, `(1,5)`, `(2,5)`, `(0,9)`; this change admits none of them.

The original table covers source labels 0–7 only. A separate 896-row even-slice
survey covers more sites and high even sources but uses a different probe
contract. Neither table establishes arbitrary odd-source behavior on every tile.

Reproduce the identity check by parsing the numeric OMUX/IMUX suffixes with the
divisors above. For a routed JSON, identify the cell driving `d[0]` through Q,
find that bit in the `d[1]` driver's LUT inputs, read their `NEXTPNR_BEL`s and
inspect only the `d[0]` routing. A future admission witness must bind source,
destination, input pin, actual route and image to a distinguishing observation.
An indirect route must not be counted as direct crossbar qualification.

Source byte hashes (historical open-flow evidence retained in AG32-Docs):

| File | SHA256 |
|---|---|
| `xbar_conduction.csv` | `31828a768d4e7bf9a6775b3e0503978158502c65e78b6d190ffa6d180fcf195f` |
| `xbar_pips.csv` | `75f09138a8ab1643456b57c715ebb980c3637068a7072bf0b357e9631b9aad45` |
| `cnt2_routed.json` | `da9f4aad7204ef86be22b5f0d62ebe6fc4b7aea89bd313603bd7cf337a094d14` |
| `cnt2p_routed.json` | `8d539ff3eb09f0df3018a040db459ad8b61da402702ba1c01edcc5928458a281` |

These hashes provide identity, not self-contained qualification data. No new
admission policy may cite this document as proof that a pair conducts. A future
public replacement must ship its validated evidence and consumer together.
