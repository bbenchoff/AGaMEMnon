# Boundary selector withdrawal — 2026-09-09

The RMUX27 -> RMUX20 relative rule at delta (0,3) was inferred from two
boundary observations. Its pair 2/9 identifies a different source at an
interior coordinate. The same suspect edge occurred in failing compact
addsub16 and util20 images. Individual route interventions passed while
preserving placement, then the general repair passed fresh source builds.

The graph now preserves exact coordinate observations but withdraws the
unsupported relative rule. Strict graphs lose three edges; tiered graphs
lose 75. Across base and native-control profiles, no edges were added and
no surviving row changed. The emitter separately rejects withdrawn edges
before context, admitted, relative, absolute or predictor resolution.
Removing the relative entry alone was insufficient: a trained predictor
could regenerate the same selector.

The retained SERV checkpoint uses a different coordinate of this rule.
Its reproduction exception authenticates the whole routed file, parsed
module, required environment and final decoded image. It does not admit
the same route for a changed checkpoint. Corrupted final emission is refused
and removed. Historical graph hashes remain explicit finite snapshots.

## Measured ordinary-source results

| Design | Baseline slices / tiles | Compact slices / tiles | Full silicon contract |
| --- | --- | --- | --- |
| regbank16 | 68 / 16 | 68 / 6 | Previously passed 3/3 |
| addsub16 | 151 / 26 | 151 / 12 | 4,096 observations, 3/3 |
| util20 | 434 / 41 | 434 / 39 | 1,024 observations, 3/3 |

Fresh addsub image:
`5bfdb3de75affb817e052e619933a8ad5834b45ae029f4e10dbea1d13438eddb`.
Fresh util20 image:
`731e99b03cfae327dfe23034b2deb5c4c43aafefeebd3449631cbc0ad6cd78a2`.
Both came from ordinary RTL through the build CLI, with explicit compaction,
without manual route changes. The C++ source matches the pinned native
binary's compiled source after line-ending normalization. Python engine and
graph source commit: `90667a1246770ad4fb77fe6c0987bbc750dd08a8`.

The combined SRAM session passed both controls and its reference. Both
original passing baselines passed 3/3; the original compact util20 image
reproduced its failure. A separate one-branch util20 intervention passed 3/3
and is classified as diagnostic evidence, not the source-flow qualification.
Raw mailbox audit passed; final reset and custody release completed, with
zero flash or option-byte writes. Fences remain 74.

All 58 retained images were byte-identical before updating graph fingerprints.
The normal new-graph retained suite then passed all 60 tests. Focused routing,
replay and control tests passed 123 tests; seven graph identity/tamper tests
also passed. These finite results do not establish arbitrary-design vendor
parity, general mixed-control qualification, or physical speed improvement.
Compaction was subsequently promoted with placement preflight and fallback;
see [ordinary default qualification](DEFAULT_TILE_PACKING.md). Expanded
control sharing remains explicit. No release is created by this change.

## RMUX92 downward turnback — 2026-09-18

The relative `RMUX92 -> RMUX74` rule at delta `(0,-1)` is also withdrawn.
Its supporting observations are confined to destination rows 2 and 3.
At `X19Y11_RMUX74`, the inferred selector pair `6/9` leaves a minimal
four-cell toggle observer high. With both candidate source branches
configured, changing only that selector to the exact `X19Y8_RMUX92`
reference (`1/9`, two payload bits) restores 5 MHz in three alternating
SRAM trials. A separate local observer verifies the disputed
`X19Y12_RMUX92` source prefix; clearing its selector stops the signal.
The before/after rig controls pass and flash readback is unchanged.

This refuses an unsupported translation while preserving every exact
coordinate observation. The diagnostic images establish this selector
failure; they do not qualify a fresh whole-design build or imply that
every other unobserved selector is safe. Passing/failing paired images:
`4cdd9b3800cdec2678ee9b687882b20eed9d661aa9f33ea5137d96c071e3862f` /
`297893ea5912972ed651864ad2849cc96eaa5cd5049b7b150830f50211154946`.

## RMUX93 rightward turnback — 2026-09-18

The relative `RMUX93 -> RMUX87` rule at delta `(1,0)` is withdrawn too.
Its exact observations occur only at destination columns 3 and 16. A fresh
tiered accumulator exposed a failing four-cell output path at
`X18Y10_RMUX93 -> X19Y10_RMUX87`. Independent source-prefix and output-buffer
controls pass; clearing the source selector stops the prefix control.
With both source branches configured, three alternating trials switch between
stuck high and 5 MHz by changing only two RMUX87 payload bits: inferred pair
`5/8` versus exact `X17Y10_RMUX45` pair `3/8`. The adjacent suspected downward
hop conducts and remains admitted. Flash readback is unchanged.

Only unsupported translations are refused; all exact observations remain.
This is a localized selector diagnosis, not whole-design qualification.
Passing/failing paired images:
`b07127aac4883b8aa7bea2cfee2385b5306d68c8befa7b6ce2fd285cc13bfb67` /
`344e8999fb629bd3b9275554245bdca5f775cbec01da4e682e11055ab6eba745`.

## RMUX69 same-tile turnback to RMUX87 — 2026-09-18

The relative `RMUX69 -> RMUX87` rule at delta `(0,0)` is withdrawn.
Its exact observations occur at destination rows 3, 4 and 11, pair `5/9`.
At `X17Y10`, a seven-cell diagnostic reads high for both forced source
levels. An exact-observation path from the same RMUX69 source prefix,
through `X17Y12_RMUX86`, `X15Y12_RMUX57` and `X15Y10_RMUX45`, rejoins
the original suffix at RMUX87 and correctly distinguishes zero from one.

Keeping both branches configured and restoring only the four RMUX87
selector payload bits reproduces the failure in three alternating pairs.
Clearing the shared RMUX69 source selector also breaks the reference.
All reference and rig controls pass under both output pull biases;
the SRAM-only session ends with unchanged flash readback and a clean reset.
Passing/failing source-zero paired images:
`01698ef5aca04b3006bf6b163e183070858dafd859aae57bd37d7f825cd3c7d4` /
`2650c044e6e0c70e67f406b9a22f0ad4e238a0244f22859ce2e2c871fb080477`.

Exact coordinate observations remain admitted. This rejects an unsupported
translation; it does not establish that every possible encoding is absent,
or qualify the complete SERV design from which the diagnostic was reduced.
Source-fresh base and shared-control graphs each lose exactly six strict
or 123 tiered inferred edges, with every surviving row unchanged. Exact
predecessor graph identities remain available for historical replay, while
the emitter independently refuses this translation before writing an image.

## Two further clear-input translations — 2026-09-18

Two more relative rules are withdrawn while preserving every exact coordinate
observation:

- `RMUX33 -> RMUX39`, delta `(1,0)`, inferred pair `5/8`. Its observations
  occur only at destination columns 3 and 16. An independent observation of
  `X17Y9_RMUX33` correctly carries both forced source levels, but the inferred
  input at `X18Y9_RMUX39` reads high for both. With an exact output path and
  both source branches configured, changing only two target-selector bits to
  exact `X19Y9_RMUX33` pair `5/7` restores source delivery in three alternating
  board pairs. Cutting the common RMUX33 source also breaks the reference.
- `RMUX69 -> RMUX83`, delta `(0,-1)`, inferred pair `6/9`. Its observations
  occur at destination rows 2, 3 and 10. With the preceding RMUX39 input
  corrected, `X18Y10_RMUX69 -> X18Y9_RMUX83` still reads high for both source
  levels. An exact alternate from that same RMUX69, through `X18Y12_RMUX86`,
  `X16Y12_RMUX57` and `X16Y9_RMUX45`, restores delivery. Reverting only four
  RMUX83 bits from exact pair `3/8` reproduces failure in three board pairs;
  cutting the common source breaks the reference too.

The first RMUX39 reference retained the faulty downstream RMUX83 connection
and therefore also failed. The later independent output path removes that
confound before attributing the two failures to their respective selectors.
All final reference controls pass under both output pull biases. The SRAM-only
sessions end with pins released, clean resets and unchanged flash readback.

Passing/failing source-zero image pairs, with only the named selector changed:

| Selector | Passing image SHA-256 | Failing image SHA-256 |
|---|---|---|
| RMUX39 | `9a9281b2fe58fb7034df430211ab160d591674705aaab6c023d5a13e6ad63b57` | `67ff8e9d10adfc685acc98a07397afb97bcf55eaa7a8f4274a15aa8625e462c6` |
| RMUX83 | `018509eb5f46bc9624ac28658b186086c968dbbfd981c480cf6b5ca291533204` | `e292c2741727342e876c5a9c1f0276a51b91e48a9d9ce0b8ec67fc16dbda1221` |

These are localized selector diagnoses. An independently controlled exact
clear-input route still does not repair the complete SERV design; whole-design
qualification and other unobserved translations remain open.
Source-fresh base and shared-control graphs each remove exactly two strict
or 202 tiered inferred edges, with every surviving row unchanged. Exact
predecessor identities remain available for replay; new emission independently
rejects both withdrawn translations even when using a historical graph.

## RMUX85 to RMUX65 downward translation — 2026-09-18

The relative `RMUX85 -> RMUX65` rule at delta `(0,-1)`, pair `6/9`, is
withdrawn outside its exact observations at destination rows 2, 3 and 10.
At `X18Y10_RMUX85 -> X18Y9_RMUX65`, the original input reads high for both
forced source levels. An independent observation of the RMUX85 prefix
correctly delivers both levels. An exact alternate from the same upstream
logical source `X17Y10_RMUX69`, through `X17Y12_RMUX86`, `X15Y12_RMUX50`,
`X15Y11_RMUX08` and `X18Y11_RMUX37`, restores delivery to RMUX65.

With both branches configured, changing only two target-selector bits from
exact pair `4/9` back to inferred `6/9` reproduces failure in three alternating
board pairs. Cutting the common upstream source breaks the reference;
cutting RMUX85 breaks its independent prefix observation. Both output pull
biases agree. The passing and failing source-zero images differ only in the
named selector field and the regenerated CRC:

- Passing: `27c49e28ef9858ec5010e1e14bc10e839769374d778af6fce5048c9ae2a764e0`
- Failing: `0f90ee793e4816502918fed684b3ff68a28b5babae96d7a8e1f539522d3f9cb0`

Source-fresh base and shared-control graphs each lose 95 tiered inferred
edges. Strict graphs and all surviving rows are unchanged. Exact historical
graph identities remain available for replay; new emission refuses this
translation even with a historical graph. Exact coordinate observations are
preserved. The same investigation verifies the preceding RMUX92 to RMUX81
instance delivers both levels, so that rule remains admitted.

These SRAM-only controls establish a localized selector defect. The complete
SERV design still fails its functional contract after a controlled exact
clear-input replacement. The broader routing and toolchain objectives remain
open. Pins were released, the board reset cleanly, and flash readback was
unchanged after the diagnostic session.
