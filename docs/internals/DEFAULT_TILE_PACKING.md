# Ordinary routing-aware placement

Ordinary `build --uarch` now enables tile compaction, control-group
repartitioning and carry-ingress preflight. No environment override is needed.
These policies preserve the architecture's placement and routing predicates.

An impossible native-enable group may be split into smaller groups, each
rechecked for a complete simultaneous assignment and enable-driver reachability.
If no typed carry footprint has ingress for every connected data input, the
existing flow rebuilds with LUT carry, unless hard carry was explicitly
requested. Compaction moves legal clusters after placement. If its complete
placement/routing ladder exhausts with classified failures, an ordinary build
can retry once without compaction. Abort, timing and unclassified failures
do not authorize that retry.

Explicit environment values are preserved. Qualified checkpoint/BRAM,
replay and research profiles retain their settings. Automatic preflight preserves explicit mixed/dual controls. Ordinary builds
also compare profitable sharing profiles; see [selection policy](CONTROL_SHARING_SELECTION.md). Direct nextpnr entry points retain their
explicit switches. `AGRV2K_TILE_COMPACT=0` disables ordinary CLI compaction.

## Fresh-source qualification, September 9

| Design | Slices | Occupied tiles | Original full contract |
| --- | ---: | ---: | --- |
| regbank16 | 68 | 6 | 3/3 pass |
| addsub16 | 151 | 12 | 3/3 pass |
| util20 | 434 | 39 | 3/3 pass |

All builds used ordinary mapping defaults. The candidate comparison selected
the smaller completed mapping; addsub16's recovered mapping uses 151 slices
versus the legacy candidate's 157. No manual route edits were used.

Images, respectively:

- `8eeb228087f2d0e1828a1343540c7a5586b3198780dcaa083473ac66355d0b5e`
- `5bfdb3de75affb817e052e619933a8ad5834b45ae029f4e10dbea1d13438eddb`
- `731e99b03cfae327dfe23034b2deb5c4c43aafefeebd3449631cbc0ad6cd78a2`

Engine source: `7581b382d5153b146529a8e72362d39fa729aa76`.
Native binary: `f27568a8732e88255d0e54052382bfc4ead01b99c06af85b6abe868d3c6d3512`.
The SRAM session passed all 18 baseline/candidate runs, both controls and its
reference. The raw-mailbox audit passed; final reset and custody release were
verified, with no flash or option-byte writes. Result SHA256:
`bdfc789e24ee43b0e711a312ab2630c09e281e3f80e5a9c42993e32f76935606`.

All 58 retained images remain byte-identical (60 regression tests passed),
and 90 focused default/fallback tests passed. Fences remain 74. This does not
establish physical speed, arbitrary-design vendor density, or arbitrary control
compositions. Denser util20 placements still encounter routing
failures. No release is created by this main-branch update.
