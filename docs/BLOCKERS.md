# Integrated v0.4.0 release gates — 2026-09-07

This candidate is unpublished. These are the remaining gates for the incremental v0.4.0 release. General vendor parity is a longer-term objective; the functional limitations below are explicit release boundaries, not promises to fix every hardware surface before v0.4.0.

## Remaining release gates

| Gate | Current evidence | Remaining work |
|---|---|---|
| Final compiled and source regression | Prior candidate full CI `34089341861` passed all eight jobs. Default odd-source images reproduce exactly; three native mode tests pass; two obsolete native even-only assertions were corrected and pass | The corrected complete native gate passes 270 tests with zero skips. Replacement CI `34097318152` passes its compiled end-to-end build and installed-wheel jobs; the full source suites remain running; the prior CI preserved two obsolete parity-assertion failures and was cancelled after their repair |
| SDK archives | Required runtime topology tables are packaged. The stale SDK preflight was corrected and passes the actual installed candidate wheel | Replacement SDK run `34097320224` must assemble and exercise complete Windows/Linux archives; previous run `34089520106` passed regressions but failed assembly, so it was not an archive pass |
| Remaining integration and documentation | Required-route reservations, BRAM source/ground-route repairs, public input validation and ordinary odd-site defaults are integrated. Documentation has a tracked read/edit inventory | Review remaining unique branch changes, integrate completed substantiated work, preserve unfinished experiments, reconcile the remaining documentation and final artifact identities |
| Worktree and branch consolidation | One hundred worktrees have been retired: 102 originally, two remain. Seventy-two local branches have been retired: 74 to two. Fifty-seven redundant remote branches were also removed. Recovery tips, bundles and checkout archives are banked | After publication, fast-forward the preserved primary checkout to the release and retire the candidate checkout and branch; historical HIL paths have complete recovery instructions |
| Publication | OpenOCD dependency is published and publicly installable. The v0.4.0 toolchain release is not published | Publish the validated integrated release and reproducible artifacts, then verify their public downloads and installation |

## Completed capabilities and release evidence

- **Ordinary odd-site defaults:** source-typed ownership is the normal native model. Fresh installed regbank16 and util20 builds without an experimental variable match the hardware-tested raw and compressed images exactly. Explicit `AGRV2K_SOURCE_TYPED_XBAR=0` preserves legacy placement behavior; malformed values fail. This changes no graph edges or negative fences. See [default verification](../qualification/ODD_DEFAULT_REPRODUCTION_20260907.md).
- **Scoped BRAM reproducibility:** all four installed ordinary source profiles reproduce their qualified raw/compressed hashes after the ground-route repair. This closes that reproducibility defect, not general RAM support.
- **Installed public SRAM programming:** all five reference/candidate arms pass; raw mailbox vectors and 2,343 input bindings were audited. Final reset succeeded and custody was released; flash and option-byte writes were zero. See [exact scope](../qualification/INSTALLED_PUBLIC_SRAM_20260906.md).
- **OpenOCD dependency:** `openocd-v0.1.0` is published. All four platform builds and identical corresponding-source archives passed verification. All 1,089 Windows runtime files match the hardware-tested package. Anonymous default-URL installations into empty Windows and Linux homes passed, with matching archive hashes and boardless configuration checks.
- **Retained bytes:** the immutable original and migrated image manifests remain reproducible through their documented paths. No image pin was changed to conceal a regression. The current default gate passes all 58 migrated pins plus manifest coverage (59 tests, 412.03 s); authenticated historical replay passes all 58 original pins (499.5 s). Seventeen original/default versions differ. The initial historical invocation failed its policy gate without an image; the successful retry explicitly used the documented replay mode and `--research-unsafe`.

## Explicit remaining functional limitations

| Area | Boundary for this release |
|---|---|
| Width and density | Passing util20 uses 442 cells over 102 tiles; compact 42-tile routing times out. Regbank16 uses 68 cells over 16 tiles. Addsub16 still times out without an image. Default odd support does not establish vendor-comparable capacity |
| Memory | Characterized read-only modes and bounded write profiles do not qualify general inferred writable/dual-port RAM, other sites/clocks or collision behavior |
| I/O and register control | Preserve exact admitted pads, routes and control compositions; arbitrary I/O, direct-D sites and mixed controls remain unqualified |
| Clock and timing | Partial timing estimates and bounded clock evidence do not provide broad sign-off, arbitrary clock reach or a general Fmax guarantee |
| Correctness | All 74 retained negative entries remain fenced. A successful build or an image absent from that registry is not a universal silicon-correctness guarantee |

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

Current SDK checkpoint (2026-09-07): run `34089520106` failed archive assembly after passing its regression stage. Commit `348f94f` corrected the stale classification of the two required normalized runtime tables; the actual candidate-wheel preflight now passes. Run `34094652131` was cancelled after independently reproducing a release-note test failure. The corrected replacement `34097320224` is running; complete Windows/Linux archive validation remains open.
