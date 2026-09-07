# Integrated release blockers — 2026-09-07

This is the working blocker snapshot for the integrated v0.4.0 candidate, not a published support certification. Historical campaign success counts are not substituted for the gates below.

| Area | Current evidence | Required next gate |
|---|---|---|
| Ordinary odd slices and local Qin | Fresh regbank16 and util20 pass sampled silicon contracts 3/3 each, with passing references and controls; zero feedback buffers in both. An isolated wheel of a99f965 rebuilds both ordinary sources to those exact raw/compressed images | **Promote the verified odd-slice implementation into the normal flow, with admission tests and an explicit bounded scope.** Until that work is complete, odd slices remain experimental; broader sites, compositions and clocks remain unqualified |
| Width and density | util20 emits at 442 cells / 102 tiles; compact 42-tile placement times out during routing. regbank16 emits at 68 cells / 16 tiles. addsub16 times out without an image | Resolve compact routing and addsub16 failure or explicitly retain these release limitations; placement alone is not a width repair |
| Retained bytes | Default matches 58 migrated pins; explicit authenticated research replay matches 58 original pins. Seventeen default/original images differ | **Completed gate.** Preserve both immutable manifests and replay distinction in release evidence; this is no longer an unresolved blocker |
| Compiled regression and CI | Corrected CI `34089341861` at `9c34aa21c9dc855d768418f298cccd1f95ad67fa` completed successfully across all eight jobs: Python 3.9/3.11/3.12, Windows, installed-wheel platforms and native end-to-end | **Completed gate.** Keep the terminal workflow record and its skip accounting in release evidence; SDK archive assembly and smoke testing remain tracked below |
| Installation and release artifacts | Isolated wheel repacking passed; missing routing datasets packaged. Versioning and tag-bound notes integrated | Ground-route reproducibility repaired: all four installed source profiles match their qualified raw/compressed hashes. Complete independently packaged SDK archives, programming and broader workflow gates |
| Programming | Installed public SRAM CLI passed all five reference/candidate arms; raw vectors and 2,343 bindings audited. Zero flash/option writes; fences 74 -> 74. [Exact scope](../qualification/INSTALLED_PUBLIC_SRAM_20260906.md) | **Hardware gate completed for this bounded SRAM contract.** OpenOCD `34088837146` passed all four platform builds and `verify-artifacts`; the published `openocd-v0.1.0` Windows runtime matches the hardware-tested runtime byte-for-byte across 1,089 files. Clean public empty-home installations now pass on Windows and Linux, with archive hashes matching the published verified set. Complete SDK archive validation remains separate |
| Memory, I/O, register control and timing | Existing scoped evidence is retained; latest odd batch provides no new general RAM, all-I/O, all-control or timing claim | Reconcile individual capability records and remaining branch changes. Broad timing closure and vendor-comparable capacity remain unproven |
| Remaining integration | Release preparation and input-boundary validation incorporated; clean database fixtures, wheel installation in CI and compiled-native gate already present | Required-route reservation and corrected BRAM-source release-branch changes are integrated. Review and reconcile unique work from other branches, then refresh all release documentation |
| Worktree consolidation | Inventory began at 102 worktrees, 17 dirty. Four clean, artifact-free ancestral checkouts have been retired; 98 remain | Preserve unique commits, uncommitted files and ignored evidence before retirement. Four removals have banked recovery identities; no branch or unique artifact was deleted |

## Completed release evidence

These rows were previously listed as blockers and now have their required
bounded evidence. They remain part of the v0.4.0 release record, but should not
be presented as open obstacles:

- Retained-image reproduction: default migrated-pin replay and authenticated
  original-pin replay both pass 58/58 with immutable manifests.
- Corrected CI: workflow `34089341861` is green across all eight required jobs.
- Installed public SRAM programming: five control/candidate arms pass with
  zero flash or option-byte writes, final reset and custody release; the fence
  count remains 74.
- OpenOCD build and source correspondence: workflow `34088837146` passed all
  four platforms and `verify-artifacts`; the tested Windows runtime is the
  published runtime identity. Anonymous public installation into empty homes now passes on Windows and Linux.

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

Native, endpoint, retained and worktree-refresh artifacts are retained in AG32-Docs under `tools/vendor_parity/gpt6_release_*_20260906/` and `gpt6_xbar_release_endpoint_retained_20260906/`. Vendor evidence stays there. No v0.4.0 publication, all-site qualification, universal timing guarantee or fence closure is claimed by this snapshot; the separate OpenOCD release is published.

Current SDK checkpoint (2026-09-07): run `34089520106` finished with both platforms failing archive assembly because the bundle preflight still classifies two required normalized runtime tables as research-only. Its earlier regression stage passed. The bundle classification fix and final archive validation remain open. This supersedes earlier statements that this run is still active.
