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
Compaction and expanded control sharing remain explicit options. No release
is created by this change.
