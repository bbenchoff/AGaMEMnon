# v0.4.0 branch cleanup

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
