# v0.4.0 release validation

**Integration update, 2026-09-06:** the runs below belong to the earlier release
branch and do not validate the current integrated candidate. Release preparation,
tag-bound notes and the exact sanitizer path fix have been incorporated into the
odd/Qin candidate. Current bounded silicon results are recorded in
[ordinary odd contracts](../qualification/ORDINARY_ODD_CONTRACTS_20260906.md);
the full integrated artifact/workflow gates remain pending. No release is
published by changing the package version to 0.4.0.

The integrated focused run of `test_release_notes`, `test_path_policy`,
`test_openocd_bundle` and `test_sdk_workflow` passed **79 tests in 38.02 s**.
The path scan passed **1,649 files**, and tag-bound release-note rendering
completed. These checks cover release infrastructure; they are not full
installed synthesis, native routing, programming or archive qualification.

Release implementation baseline: `aa1201158eb34da35b10e7c9402abf9b8599d726`.
Release preparation does not include later compiler development.

## Retained candidate d74e7b5

[CI run 34008791528](https://github.com/bbenchoff/AGaMEMnon/actions/runs/34008791528)
stopped its Python matrix and Windows suite before pytest at the path-leak
gate. Six lines were false positives: three exact forbidden-prefix lists in
retained checkpoint sanitizers and three synthetic Windows-path test lines.
No production path, compiler setting or negative-image fence caused this
failure. Installed-wheel checks passed on Linux, Windows and macOS arm64.

The correction admits only the exact SHA-256-bound guard line in the three
named sanitizers; a changed line or the same text in another file still fails.
The normalization test now uses a generic synthetic root while testing the
same Windows, POSIX and MSYS variants. Regressions explicitly reject an actual
home path appended to the otherwise admitted guard. No historical checkpoint
sanitizer or its artifact bytes changed.

After correction, the repository path scan passed 1,622 files and the focused
docs/version/bundle/notes/path-policy/R6 normalization suite passed 174 tests.
These are local checks, not a substitute for rerun full candidate CI and SDK
archive gates. The earlier
[SDK run 34008792421](https://github.com/bbenchoff/AGaMEMnon/actions/runs/34008792421)
is retained as evidence for its exact commit, never relabeled as a newer run.

README bytes before `## Quick start` were unchanged from the implementation
baseline: SHA-256 `c9ff29d3def022c800b463291cbb541fd917d045b0126f2fab1aff9f1ea58583`.

## Publication rule

Candidate `5e8375f` passed the path gate and installed-wheel checks on all three
hosts. Its native end-to-end job then exposed a real release inconsistency:
the ordinary PIN15/PIN10 AND design placed and routed, but Python emission
refused physical input `X20Y13_IPAD1`. The validator recognized legacy IO and
bidirectional IOB names but omitted IPAD names emitted by the native packer.
The exact failure is retained in
[job 101421208672](https://github.com/bbenchoff/AGaMEMnon/actions/runs/34008931978/job/101421208672).

The repair admits only characterized physical-input rows joined to unique,
matching L48 bond-map records. The oscillator pseudo-pin is excluded. Identity
shape, scalar port direction and ownership checks are unchanged; unlisted
physical pads still refuse. Fresh source-build and retained-image replay gates
remain required after this repair.

The focused validator run passed 59 tests (61 unrelated tests deselected).
An exact old/new function comparison adds only the eleven characterized IPAD
identities and removes no legacy identity; PIN10 was absent before and present
after the repair. Repeated verified-pin rows for different characterized paths
remain valid; missing, duplicate or malformed bond identities refuse.

## Publication gates

The release job requires the wheel and both SDK jobs, archive SHA-256 checks,
tag/version agreement and an existing version-specific release-notes file.
Notes link to the exact tagged tree, not mutable main. Failed or merely queued
jobs do not qualify a release. Main and the tag are not advanced until the
candidate is reviewed; branch cleanup is separately recorded in
[the recoverable ref inventory](RELEASE_BRANCH_CLEANUP_0_4_0.md).


## Integrated native and input-boundary gate, 2026-09-06

The characterized IPAD identity check from `558564f` was integrated as `b6441f6`.
The clean database fixtures (`e559fa8`), SDK wheel installation (`096c7ef`) and
compiled-native CI gate (`d90d536`) were already present; their cherry-picks
were empty and skipped.

The focused endpoint/database/gate run passed 79 tests and skipped 52 native
checks on Windows. A separate hash-bound Linux run executed all 264 compiled
native tests without skips: 261 passed and three obsolete shared-tree refusal
assertions failed. Commit `4878c2e` had intentionally introduced complete
recorded-tree negotiation without updating those earlier refusal expectations.
The retained failing packed fixtures preserve the shared consumer connection.

The tests now check preserved source identities and shared consumers, verified
BRAM paths, and a negative control with joint negotiation disabled. No compiler
behavior changed to satisfy them. The full corrected compiled suite passed
**265 tests, zero failures, zero errors, zero skips** using native binary
`c69686959617f5654fa7027b717a2e131fcc516cfad6e49a4e01eed0d90e3377` and source
`e14d55449813774d573928b9644fa8dc76b83acba686b8de1739d218dbc23c35`.
These are pack/route tests, not new silicon qualification.

A fresh full default-emitter audit after the input-boundary change passed
**58/58 migrated pins** in 220.32 seconds; both manifests remained unchanged.
It matched 41/58 original pins, consistent with the separately documented
explicit historical replay requirement. That historical replay was not rerun
in this checkpoint. Fences remain **74 -> 74**. See [current blockers](BLOCKERS.md).


## Required-route and installed-source integration, 2026-09-06

Release-branch changes `d0972e6` and `5b837e9` were integrated as `61780ed`
and `294cef3`. The native build succeeded with source SHA256
`eda257c26dd023a53028723f96fc8f67fb1d3c27523bca427bd2d87f5a87252e`
and binary SHA256 `a2a8d87c6d673ac97eeb79c40201a3678fb233fccbfa67e240405702b94163ff`.
The shared build source/binary were restored. Focused Python tests passed 43/43.

The complete native run executed 270 tests without skips: 269 passed and one
wrong-root fixture failed only because an earlier mandatory-BRAM-prefix guard
rejected it before the expected placed-driver guard. No image was emitted.
The assertion now accepts either specific ownership/root rejection, still
requires failure and no output, and all five route-import tests passed in the
focused rerun. The original 270-test result remains recorded as failed; it is
not relabeled as a new full-suite pass.

A clean source archive produced a 0.4.0 wheel, installed offline into an empty
Linux virtual environment. Installed imports and default/original carry repacks
passed. Wheel SHA256:
`fefcb30c67373083dfad90d952df9c299924f18a5188806a639f0809e650ead6`.
The first installed source profile, `bram-tmux9-i0-d1-we1`, completed synthesis,
routing and emission, but its final hash guard correctly failed:

- Expected raw: `41e5e304e2300a949d3be969149af5b6c195e25a3b1bf4e9e03ddd093756edd0`.
- Observed raw in the guard log: `81d324576b0ae3b191cc4035ff93b0a3c8675d28d6897e8b80ca35fb529aadc7`.

The CLI removed the rejected image. Its failed routed inputs and logs are
preserved in AG32-Docs. Comparison with the qualified source reference finds
identical cell types, parameters, placement attributes and connectivity under
bijective signal-ID renumbering; only `$PACKER_GND_NET` routing differs (20
removed hops, 14 added). The five required signal-tree reservations omit this
constant tree. This is a structural diagnosis, not a counterfactual emission
proof or a silicon result. Preserve the qualified ground tree and verify exact
reproduction before allowing this installed source workflow. Do not repin the
hash or undo required ground connections. The remaining three source profiles
were not run after the first failure.

Evidence: AG32-Docs `gpt6_release_routes_native_20260906`,
`gpt6_release_routes_python_20260906`, `gpt6_release_routes_native_tests_20260906`,
`gpt6_release_required_routes_corrected_20260906`, and
`gpt6_release_installed_source_20260906`. Fences remain 74; no hardware was used.


## Qualified ground-tree repair and installed source results

The ground-only counterfactual reproduced both the rejected baseline hash and,
with only the qualified ground route restored, the expected qualified hash.
Fix `ee6e5cd` extends source-mode canonicalization to include the measured ground
tree. It validates a unique zero-valued combinational driver at the expected
source BEL and rejects collisions with signal trees or other routed nets before
writing. Historical checkpoint canonicalization keeps its previous default.
Neither raw/compressed qualification hashes nor retained-image pins changed.

The focused suite passed 59 tests. The first test-fixture attempt incorrectly
used legacy checkpoint ground placements; those were correctly rejected and
are retained as six fixture failures. Corrected source-placement fixtures test
successful replacement and atomic refusal of nonconstant, wrong-source and
foreign-owner cases.

A clean archive produced a wheel that was installed offline into an empty Linux
virtual environment. Installed default and original carry repacks passed.
Both INIT0 profiles then passed exact source-to-bitstream builds. The harness
initially chose the legacy filename for INIT1 and was rejected before synthesis;
using the installed registry's `source_build` filenames, both INIT1 profiles also
passed. All four raw and compressed identities match the existing silicon record.
The failed invocation remains recorded separately from the passing continuation.

Wheel SHA256: `45eb64c5988f1e0b6db17767a91d5333aa9dccf927cc774912727d397d7917e7`.
Native binary/source are unchanged from the preceding required-route integration.
Evidence is in AG32-Docs `gpt6_release_ground_counterfactual_20260906`,
`gpt6_release_ground_python_corrected_20260906`,
`gpt6_release_installed_ground_20260906`,
`gpt6_release_installed_ground_init1_20260906` and the independently checked
four-image summary `gpt6_release_ground_resolution_20260906/RESULT.json`.
This resolves that source reproducibility blocker; it does not establish general
RAM support, a complete SDK archive, or independent programming qualification.
Fences remain **74 -> 74**, with no new hardware session.
