# v0.4.0 branch cleanup

This is a historical 2026-09-05 remote-ref inventory, not a current worktree
deletion instruction. The later inventory found 102 local worktrees, 17 dirty.
Revalidate ownership, unique commits, uncommitted files and archived evidence
before retiring any checkout. No local worktree was removed by the 2026-09-06
release-preparation integration.

These 18 remote branch tips were verified as ancestors of `origin/main`
(`ea4d502f0c4d2d6dc300822c7ee06978bd35164e`) on 2026-09-05 and had no
owning worktree. Removing their branch names does not delete their commits:
all remain in main's history. Local worktrees, unmerged branches, main and
active development branches are preserved.

To recover a name, use `git branch <name> <commit>` followed, if needed, by
`git push origin <name>`. The table is the exact deletion allow-list.

| Branch | Retained commit |
|---|---|
| review/pll-expanded-profiles | bad1c833602d18906cf8d9fe26637283aaf7eab7 |
| review/s1-rmux30-padfeed-metadata | 77f576047ca018d91e71e13f22525f70f99843c6 |
| review/s2-packaging-audit | 643ceb2a14823aebfdbd2c8411b1cce15a069fac |
| review/s2-serv-macos | ad2c6803086bc12f44a143f9f273ba988b4ea3f1 |
| review/timing-exact-safe | f7b7513a2d1a5cf9495221c0d65c5f146bf31b41 |
| review/v6-bram-b4 | d669066b292cc1ca529b11d62fd9d43e6bb0541a |
| work/native-direct-d-pool-n5-4 | f607c25ba0b3e182830171511de2d1a02d799ef2 |
| work/native-direct-d-pool-n5-4-corrective | e0f460282ec683a6a58b1cb9b0f83d330a7187dc |
| work/native-direct-d-pool-n5-4-cross-surface-corrective | 3a76d4d820843651414ac246f7d17c14c1a9e47d |
| work/native-direct-d-pool-n5-4-top-tie-corrective | d98359d93a07a73700a3629d42357583e3097053 |
| work/native-endpoint-legality-n5-1 | f6055a891a31e07ab4893d88fa3a1fc2ab587c64 |
| work/native-endpoint-legality-n5-2 | 1634b122879d75b46fe956709d493d1c2cbfc94e |
| work/native-endpoint-legality-n5-2-failclosed | 6549fd4f17424b73ec59cda2147a5c0c5059f1c9 |
| work/native-pad-isolation-n5-3 | 5d6103fcce26f20d45ba390cf73b53f127049ebe |
| work/register-feedthrough-n3 | 264b0f6e4da314a06b304c4fdd697f303f598ebf |
| work/register-feedthrough-n3-v2 | c309deab78a5502aa0ecffe5b28b105b1e071e1f |
| work/shared-clock-legality-n1 | defcabe0223e86314dde071f3db0e72ca7114993 |
| work/shared-control-legality-n4-1 | b98e13108672bb12f6c9afe75a1f931474e83e72 |


## Verified local retirements, 2026-09-06

Four redundant checkouts were removed after checking clean tracked state,
absence of untracked and ignored artifacts, no hidden assume-unchanged/skip-worktree
entries, and ancestry to the verified pushed candidate `4d574ab`. Recovery
identities were banked in AG32-Docs commit `3dd26d923` before removal, at
`tools/vendor_parity/gpt6_release_retirement_20260906/PREPARED.json`.
The resulting count is **102 -> 98**. No branches or unique artifacts were deleted.
The remaining dirty and artifact-bearing checkouts still require preservation.

## Further verified retirements, 2026-09-07

Thirteen merged local branches without owning worktrees were removed after banking their exact recovery tips. Two obsolete local experiment branches were then preserved in a verified Git bundle and retired: their completed changes are patch-equivalent in the release candidate; their unique BRAM driver-replication patch remains an unfinished experiment with no emitted image or silicon qualification. Local branches decreased from 74 to 59. Recovery is banked in AG32-Docs under `gpt6_release_branch_retirement_20260907` and `gpt6_release_branch_archive_20260907`.

Three additional detached ancestor worktrees were removed after archiving every ignored/untracked file and administrative record. An independent audit matched archive members to the live files and rehashed every present tracked file, including sparse-checkout entries. That batch reduced the worktree count to 95 (102 originally). The archives and retirement results are banked in AG32-Docs commits b31379246 and 7a522e5f7 under `gpt6_release_worktree_archive_20260907/batch1`. No unique changes were discarded. Remaining worktrees and branches still require integration or preservation before retirement.

The next verified batches retired five more archived local branch lines and the redundant remote routing-admission branch, followed by ten archived worktrees and their two local branches (one also remote). That checkpoint left **85 worktrees and 52 local branches**, down from 102 and 74. The two remote deletions used exact-tip leases. Recovery bundles, archive checks and terminal deletion records are banked through AG32-Docs commit `2d9663012`. Historical canvas rescue evidence was reviewed and is already subsumed by current design-neutral generation and retained x9 evidence; its original lineage remains in the recovery bundle.

The independently verified third archive batch retired eleven more ancestor worktrees, seven local branches and three matching remote branches. That checkpoint left **74 worktrees and 45 local branches**, down from 102 and 74. Every ignored/untracked file and Git administrative record was preserved; a second live audit also rehashed all present tracked files before deletion. Recovery archives were pushed as AG32-Docs `d682a6b7e` before removal, and terminal retirement records as `99ce879bc`, under `gpt6_release_worktree_archive_20260907/batch3`. Remote deletions used exact-tip leases. Remaining divergent and dirty work is still being reviewed.

The reviewed n55 dirty checkout was then retired after archiving all 1,442 files, its staged safety patch and unique-history bundle. Five more clean ancestor checkouts and four local branches (two also remote) were retired after independent live-byte checks. That checkpoint left **68 worktrees and 41 local branches**, with seven remote branches retired during this consolidation. The first dirty recovery is banked at AG32-Docs `171df1282`; the five clean archives at `5ae141d0b`. Failed nested-repository archive attempts were refused and those checkouts remain present pending a complete archive.

The corrected nested archives, five full divergent archives and four further ancestor archives have now been retired. That checkpoint left **56 worktrees and 32 local branches**, with thirteen remote branches removed during this consolidation. Two external nextpnr junction targets were explicitly preserved; only their links inside the retired AGaMEMnon checkouts were removed. Exact recovery identities and complete divergent-history bundles are banked in AG32-Docs through `0ed4453f7`; no missing substantiated capability was found in these reviewed histories.

Three further dirty checkouts, the two frontier ancestors and nine reviewed divergent checkouts have been retired. That checkpoint left **42 worktrees and 21 local branches**, with twenty remote branches retired during this consolidation. The earlier v0.4 branch is among the retired histories: its substantiated changes are represented in the integrated candidate. Complete recovery archives and unique-history bundles were pushed through AG32-Docs `75e9d90e7` before deletion.

Nine reviewed dirty checkouts have also been retired after preserving complete archives, patches and history. That checkpoint left **33 worktrees and 16 local branches**, with twenty-one remote branches retired during this consolidation. The unresolved-index checkout includes a separate verified recovery pack for its staged/conflict objects; no conflict was resolved by discarding work. Those archives were banked at AG32-Docs `577bbd1b4` before removal. The primary checkout and remaining HIL input paths remain available while their preservation and release dependencies are checked.

Eleven further reviewed checkouts were retired after banking complete archives and unique history at AG32-Docs `0d519aaf1`. This checkpoint leaves **22 worktrees and 10 local branches**, with twenty-six remote branches removed. A fresh independent clone restored a retired dirty n55 checkout, including all eight staged modifications, from the banked recovery archive and bundle; the recovery proof is banked at `8efd6d4a3`. Eighteen further complete checkout archives passed independent live-file audits and were banked at that commit before retirement began.

The final eighteen archived experiment checkouts have been retired, leaving **four worktrees and four local branches**: the primary checkout, release candidate, and two preserved HIL checkouts. **Ninety-eight of the original 102 worktrees are gone; seventy of 74 local branches and thirty-one remote branches have been retired.** The complete recovery archives were pushed at `8efd6d4a3`, with omitted archive-run logs banked at `2c153994a` before the last deletion gate proceeded. External nextpnr junction targets remain intact. Remaining unowned branch references and the two HIL path dependencies are under final review.

Final experiment retirement leaves **two worktrees and two local/remote branch heads: `main` and the release candidate**. In total, **100 worktrees, 72 local branches and 57 remote branches** have been retired. The final 28 reference tips (two local and 26 remote) were preserved in the verified `remaining_public_tips.bundle`, banked at AG32-Docs `9613dbb3a`, before exact-tip deletion. The two historical HIL checkouts also passed the complete live archive audit before retirement; their frozen runners can be used again after restoring the exact archived paths and satisfying their original gates. No current release job or board process depended on them. After publication, the primary checkout can advance to the integrated release and the final candidate branch can retire.
