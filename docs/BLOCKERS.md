# v0.4.0 release status and remaining limitations — 2026-09-07

Main-branch update, 2026-09-08: isolated line-0 native clock enable is now the
default for ordinary `build --uarch`, following a fresh-source 3/3 silicon
contract. Lack of any native enable path is no longer a blocker. Mixed
sequential tiles, line 1, combined controls and broader site qualification
remain open. [Scope and fallback](NATIVE_CLOCK_ENABLE_EXPERIMENT.md).
No new release was published; the v0.4.0 record below is unchanged.

## Development update — routing-aware packing

The current engine supersedes several width outcomes in the historical release
table below. Regbank16 now has a compact 68-slice/six-tile source build that
passes silicon 3/3 (previous default 68/16; vendor 69/5). After withdrawing a nonportable
selector translation, fresh ordinary-source addsub16 at 151/12 and util20 at
434/39 also pass their original full silicon contracts 3/3. Their baselines
are 151/26 and 434/41. The earlier compact images remain known failures;
the new source flow avoids the withdrawn edges and refuses their emission in
new checkpoints. This resolves those two measured compact-image failures,
not general vendor-level density or timing. Compaction and exact placement
preflight are now ordinary CLI defaults, qualified together on all three
workloads with 3/3 passing runs per image. Qualified/replay settings are
preserved. See [default placement and fallback](DEFAULT_TILE_PACKING.md).
See [repair and qualification scope](ROUTING_SELECTOR_WITHDRAWAL.md).

Mixed ordinary/native and two-native-group clock sharing have conditional
implementations and fresh source builds that reproduce their silicon-passing
images exactly. The mixed fixture reduces 69 slices/16 tiles to 69/14.
General supported admission remains open; these options are experimental.
Reset recovery on the mixed fixture separately exposes fixed MCU `hwrite`
ingress placement restrictions. The retained58 byte gate passes and fences
remain **74 -> 74**. See [scope and evidence](LOCAL_CLOCK_SHARING.md).

The following sections describe the published v0.4.0 snapshot. Worktrees and
branches have subsequently been created for the development work above.

[v0.4.0 is published](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.4.0). Its release gates are complete.
The functional limitations below remain explicit boundaries of this incremental
release; universal vendor parity is still a longer-term objective.

## Completed release closeout

- Tagged SDK workflow `34139873735` passed all four jobs and published six assets; CI `34139867923` passed all eight jobs at tag commit `76f4c0270a26d3f8debefdbec6089bda380d2391`.
- Anonymous downloads match all published hashes and sidecars. Both SDKs embed the exact published wheel. Fresh offline Windows and Linux installations pass diagnostics, routed verification, MCU/FPGA source builds and exact BRAM/profile hashes.
- Only the primary checkout and `main` branch remain. All 101 redundant worktrees, 73 local branches and 58 remote branches were retired after preserving unique work and evidence.
- All 74 negative fences remain. No additional silicon qualification or broad capacity/timing claim follows from packaging success.

## Completed capabilities and release evidence

- **SDK archives:** workflow `34097320224` passed both Windows/Linux regressions, pinned native builds and extracted archive smoke tests. All three downloaded checksums match; both archives embed exactly the published-candidate wheel. Tagged release assets are generated from the finalized source.

- **Integration and documentation audit:** substantiated changes are consolidated on public `main` at `5a25e70`. The complete documentation inventory and branch/overlay reviews are recorded; unfinished experiments are preserved in recovery archives. Final asset identities and public installation results are recorded in the release validation document.

- **Full regression:** CI `34097318152` passes all eight jobs at `dcaf28e`, including compiled native end-to-end, installed wheels on Linux/Windows/macOS, and complete source suites on Python 3.9/3.11/3.12 and Windows. The separate corrected local native gate passes 270 tests with zero skips.

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

Native, endpoint, retained and worktree-refresh artifacts are retained in AG32-Docs under `tools/vendor_parity/gpt6_release_*_20260906/` and `gpt6_xbar_release_endpoint_retained_20260906/`. Vendor evidence stays there. These historical compiler artifacts do not establish all-site qualification, universal timing or fence closure. The v0.4.0 and OpenOCD releases are now published.

Historical candidate SDK checkpoint (2026-09-07): run `34089520106` failed archive assembly after passing its regression stage. Commit `348f94f` corrected the stale classification of the two required normalized runtime tables; the actual candidate-wheel preflight now passes. Run `34094652131` was cancelled after independently reproducing a release-note test failure. The corrected replacement `34097320224` passed both platforms, and its downloaded release set passed independent checksum and embedded-wheel validation.
