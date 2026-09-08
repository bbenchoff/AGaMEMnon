# Native clock enable experiment — 2026-09-08

This branch implements experimental positive-polarity native register clock
enable. Normal v0.4.0 behavior still lowers source enables into ordinary
register data logic. The experimental path requires both
`AGRV2K_SHARED_CONTROL_ENABLE=1` and `AGRV2K_SHARED_CONTROL_GRAPH=1` and a rebuilt
nextpnr containing the supplied Viaduct cluster-placement hook patch.

## Placement repair

A control group must share a tile, but its register members need not occupy
slices 0 through N−1. The previous fixed cluster shape required exactly those
slices. Fixed MCU input reachability made those assignments illegal even where
other slots in the same tile were usable. This was not a three-control-set
hardware limit.

At the end of pre-placement preparation, the architecture now computes
per-member legal slots in each candidate tile and matches members to distinct
slots. Existing regions, fixed BELs, endpoint reachability and whole-placement
checks remain enforced. It also requires a feasible source location for the
enable-driving LUT: legal register slots alone did not ensure that the enable
net could reach its tile control sink. Callbacks use the resulting immutable
table rather than mutating bindings during parallel placement.

The existing assignment is preferred when legal. One matching is retained per
tile; this is not an exhaustive joint placement solver. Other cluster types use
the existing generic nextpnr implementation. New failures remain explicit
placement failures, with optional explained validity diagnostics.

## Encoding and compatibility

The tile-control encoder owns LogicTile control resources only. BRAM tiles
reuse some wire names and retain their existing resolver, including when the
experimental graph is enabled. Without that separation the branch intercepted
a retained BRAM enable route and refused an otherwise qualified image.

Legacy clock validation uses the canonical-LF identity already defined by its
registry. Raw-byte custody and output bindings retain their original identities.
This makes a Windows CRLF checkout reproduce the retained image without
accepting arbitrary changed inputs or updating any image pins.

## Bounded test composition

The complete ordinary-source release-strict build places and routes on attempt
1 and reproduces raw image
`4959005cdc15d60483e425c66e8040054793740cc075cd004feee41248340771`.
Eight gated data bits use X16Y10 slices 0–7 on line 0. Their LUTs are identity
functions of write data, with no data-feedback hold mux; observing hold/resume
therefore tests the native enable path. Two read-word registers use line 0 at
X16Y12. Ordinary scratch bits at X16Y10 slices 8 and 10 bypass the enable.

The preregistered experiment updates gated data to A3, attempts complementary
5C and further 39/7E writes while disabled, then resumes with 5C. During the
disabled phase, exact scratch writes and readbacks of 2020/DFDF/2020 exercise
the two ordinary neighbours. A separate LFSR supplies phase-independent
liveness observations. Always-enabled, never-enabled and collateral scratch-
gating simulation mutations are rejected.

The rebuilt native regression passes 270 tests without skips. Silicon and
retained-image terminal results are recorded separately before any supported
capability claim. Vendor comparison artifacts and board orchestration remain
in the private evidence repository.

## Remaining boundaries

Line 1, synchronous shared controls, asynchronous control admission, arbitrary
coordinates, combined modes, timing closure and general placement capacity are
not qualified by this fixture. The unexplained vendor BYPASSEN comparison stays
unexplained. A passing bounded contract does not close an unrelated silicon
fence or justify promoting the feature to the default release registry.
