# Integrated release blockers â€” 2026-09-06

This is the working blocker snapshot for the integrated v0.4.0 candidate, not a published support certification. Historical campaign success counts are not substituted for the gates below.

| Area | Current evidence | Required next gate |
|---|---|---|
| Ordinary odd slices and local Qin | Fresh regbank16 and util20 pass sampled silicon contracts 3/3 each, with passing references and controls; zero feedback buffers in both. An isolated wheel of a99f965 rebuilds both ordinary sources to those exact raw/compressed images | Admit only supported scope after reviewing general-repair evidence; broader sites, compositions and clocks remain unqualified |
| Width and density | util20 emits at 442 cells / 102 tiles; compact 42-tile placement times out during routing. regbank16 emits at 68 cells / 16 tiles. addsub16 times out without an image | Resolve compact routing and addsub16 failure or explicitly retain these release limitations; placement alone is not a width repair |
| Retained bytes | Default matches 58 migrated pins; explicit authenticated research replay matches 58 original pins. Seventeen default/original images differ | Preserve both immutable manifests and replay distinction. The fresh default audit after input-boundary integration passed 58/58 migrated pins in 220.32 seconds; manifests unchanged |
| Compiled regression and CI | Native end-to-end CI job passed. Full Windows/Python 3.12 suites each reported 2,589 pass, 592 skipped and three failures: generated ledger drift, a documentation-link false positive, and a constant-indirect registry lookup. Corrections pass 113 focused tests | Full CI rerun on the corrected candidate and terminal SDK archive gates remain required; earlier native local 269/270 result and corrected focused 5/5 remain historical evidence |
| Installation and release artifacts | Isolated wheel repacking passed; missing routing datasets packaged. Versioning and tag-bound notes integrated | Ground-route reproducibility repaired: all four installed source profiles match their qualified raw/compressed hashes. Complete independently packaged SDK archives, programming and broader workflow gates |
| Programming | Installed public SRAM CLI passed all five reference/candidate arms; raw vectors and 2,343 bindings audited. Zero flash/option writes; fences 74 -> 74. [Exact scope](../qualification/INSTALLED_PUBLIC_SRAM_20260906.md) | Publish OpenOCD after cross-platform corresponding-source identity passes. Rebuild 34088837146 remains pending; preceding all-platform build had Windows archive line-ending/mode differences. Verify public installation into an empty home and exact tested runtime identity |
| Memory, I/O, register control and timing | Existing scoped evidence is retained; latest odd batch provides no new general RAM, all-I/O, all-control or timing claim | Reconcile individual capability records and remaining branch changes. Broad timing closure and vendor-comparable capacity remain unproven |
| Remaining integration | Release preparation and input-boundary validation incorporated; clean database fixtures, wheel installation in CI and compiled-native gate already present | Required-route reservation and corrected BRAM-source release-branch changes are now integrated. Review unique work from other branches |
| Worktree consolidation | Inventory began at 102 worktrees, 17 dirty. Four clean, artifact-free ancestral checkouts have been retired; 98 remain | Preserve unique commits, uncommitted files and ignored evidence before retirement. Four removals have banked recovery identities; no branch or unique artifact was deleted |

## Negative registry snapshot

Generated from `agamemnon.engine.silicon_negatives` in the integrated checkout: **74 entries: 44 image and 30 logical, across 18 IDs**. Before/after this round: **74 -> 74; zero removed**. An ID appearing here means its retained negative remains fenced; it does not establish that every composition for that ID is wrong or that its mechanism has never been investigated. Successful bounded contracts do not automatically authorize removing these fences.

| Defect ID | Image fences | Logical fences |
|---|---:|---:|
| VP-AGM-001 | 3 | 1 |
| VP-AGM-003 | 1 | 1 |
| VP-AGM-004 | 1 | 1 |
| VP-AGM-005 | 1 | 1 |
| VP-AGM-006 | 2 | 0 |
| VP-AGM-007 | 1 | 0 |
| VP-AGM-008 | 7 | 2 |
| VP-AGM-009 | 1 | 1 |
| VP-AGM-012 | 5 | 5 |
| VP-AGM-013 | 1 | 1 |
| VP-AGM-014 | 3 | 3 |
| VP-AGM-015 | 6 | 6 |
| VP-AGM-016 | 3 | 3 |
| VP-AGM-017 | 2 | 2 |
| VP-AGM-018 | 1 | 1 |
| VP-AGM-019 | 4 | 2 |
| VP-GPT6-001 | 1 | 0 |
| VP-GPT6-002 | 1 | 0 |

## Evidence and scope

- [Ordinary odd silicon contracts](../qualification/ORDINARY_ODD_CONTRACTS_20260906.md)
- [Retained image versions](../qualification/RETAINED_IMAGE_VERSIONS.md)
- [Release validation](RELEASE_VALIDATION_0_4_0.md)
- [Draft release scope](RELEASE_0_4_0.md)

Native, endpoint, retained and worktree-refresh artifacts are retained in AG32-Docs under `tools/vendor_parity/gpt6_release_*_20260906/` and `gpt6_xbar_release_endpoint_retained_20260906/`. Vendor evidence stays there. No publication, all-site qualification, universal timing guarantee or fence closure is claimed by this snapshot.
