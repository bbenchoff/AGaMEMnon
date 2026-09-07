# v0.4.0 release validation

**Integration update, 2026-09-06:** the runs below belong to the earlier release
branch and do not validate the current integrated candidate. Release preparation,
tag-bound notes and the exact sanitizer path fix have been incorporated into the
odd/Qin candidate. Current bounded silicon results are recorded in
[ordinary odd contracts](../qualification/ORDINARY_ODD_CONTRACTS_20260906.md);
the full integrated artifact/workflow gates are tracked below. v0.4.0 remains
unpublished; changing the package version alone does not publish a release.

Current workflow checkpoint (2026-09-07): full CI `34089341861` passed all
eight jobs. OpenOCD workflow `34088837146` passed all four platforms and its
verification gate; its published target is `e913b09` with ten verified assets.
The final 1,089 Windows runtime files match the hardware-tested runtime.
SDK workflow `34089520106` completed with both platform archive-assembly
failures because `pip_usage.csv` and `rrg_rmux_imux_full.csv` were classified
as research-only. Its earlier regression stage passed. The classification fix
is integrated and passes the actual candidate-wheel preflight. Replacement
CI `34097318152` has passed its compiled end-to-end and installed-wheel jobs;
its source jobs remain live. SDK `34097320224` remains live and its terminal
archive result is not yet claimed. `34094652131` was cancelled after the
release-note test failure was independently reproduced.

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

## Public programming dependency installation

The successful wheel job from SDK run `34086252437` produced wheel SHA256
`888635be2dbd834afc870e6ac0a0859d01f1030c3dc2cfebfeec2ede23c553ef`.
Its artifact sidecar was verified, and the wheel installed offline into a new
Windows virtual environment with imports confirmed outside the checkout.
The public `openocd-v0.1.0` release is now published from target `e913b09`
with ten verified assets. The fresh Windows empty-home installation test
passed with no base URL override or authentication, downloaded the published
archive, matched the expected archive and hardware-tested binary identities,
and passed public configuration parsing with `init` intercepted. Evidence is
in AG32-Docs `gpt6_release_public_openocd_install_20260907/RESULT.json`.
The fresh Linux empty-home installation likewise passed with the default public
URL; archive identity, version, dynamic-library checks, and public
configuration parsing passed. Evidence is in AG32-Docs
`gpt6_release_public_linux_openocd_20260907/RESULT.json`.

The preceding OpenOCD workflow `33250345100` failed on MSYS/native path spelling
in Windows and on generated build files in the strict source inventory elsewhere.
Fix `5f9931f` translates MSYS Git paths before retaining both exact-path and
filesystem-object checks. The build now verifies and preserves the packaging
source and compiles a second fully verified checkout of the same pinned source.
It does not allow generated files into the source archive or weaken provenance.
The 38 local bundle tests passed, including a real Windows/MSYS path test and
a negative control for a different repository. Shell syntax and maintained
documentation checks passed. Four-platform workflow `34086984598` is retained
as superseded evidence; successful replacement `34088837146` covers publication
and installed runtime validation.

Evidence: AG32-Docs `gpt6_release_programming_install_20260906`. Its installation
result remains failed, not relabeled after the build-recipe correction. No
hardware was contacted, no image pins changed, and fences remain 74.

### OpenOCD build follow-up and SRAM result integrity

Run `34086984598` completed with a successful Linux build and three failures.
Windows now passed source preparation, then correctly rejected three changed
MSYS2 build packages. Both macOS builds compiled but rejected the OS temporary
directory alias during source packaging. Commit `0dea6bf` records the three
measured Windows build versions as exact locks and canonicalizes the temporary
parent before creating the private package workspace. Nested staging aliases
remain refused. All 39 local bundle tests passed; follow-up four-platform run
`34087211060` is superseded. Changed build tools required fresh binary
validation, which is supplied by successful workflow `34088837146`; the
previous Windows binary's qualification was not transferred automatically.

The first run's Linux archive and corresponding-source archive were downloaded
and checked against their sidecars. The fresh CI wheel installed it offline
using the installer's local mirror option in a new Linux environment. Discovery,
binary launch and packaged configuration parsing passed with `init` explicitly
intercepted. The pinned OpenOCD reports two uninitialized-target diagnostics at
shutdown; those exact diagnostics are recorded. This is a boardless artifact
installation check, not public-download availability or hardware qualification.
Evidence: AG32-Docs `gpt6_release_linux_openocd_20260906`.

Review of the public SRAM command also found that a zero OpenOCD exit status
with an incomplete mailbox printed missing words as zero. The command now
requires every requested word before reporting any result, preserves genuine
zero words, and rejects nonpositive word counts before contacting hardware.
The programming-safety suite passed 20 tests, including omitted first, middle
and last words, complete zero data, disconnect and pre-contact refusal cases.
No hardware or bitstream change was involved.

## Installed ordinary odd-source reproduction

A clean archive of `a99f96588d0dd8a8a547a4106cc9048f2941cae6` produced wheel
SHA256 `8581891d9f09206199a853cdcf8fd781fa661a15080ee9c06a06f144cd704624`.
It was installed offline into a new Linux virtual environment and imported
outside the source checkout. Fresh regbank16 and util20 builds, using their
unchanged ordinary sources, experimental source-typed odd option and strict
graph admission, both completed and reproduced the raw and compressed images
from the prior passing silicon batch exactly. Neither image was substituted
from the retained files and no hash was repinned.

The separately supplied native executable was bound to this candidate's C++
source and SHA256 `a2a8d87c6d673ac97eeb79c40201a3678fb233fccbfa67e240405702b94163ff`.
This extends the installed-source check beyond the four exact BRAM profiles.
It is not a full SDK archive test or a new board session. The existing bounded
silicon contracts, experimental admission and width/timing limitations remain
unchanged. Fences remain 74. Evidence: AG32-Docs
`gpt6_release_installed_odd_20260906/RESULT.json` and its build logs/artifacts.

## Installed public programming checkpoint

The actual installed SRAM CLI passed the five-arm public OpenOCD session, including fresh regbank16 and util20 images and controls before/after. See [exact identities and scope](../qualification/INSTALLED_PUBLIC_SRAM_20260906.md). This closes that bounded hardware exercise; Windows and Linux empty-home public OpenOCD installation checks also passed, while complete SDK gates remain open.

Current workflow checkpoint (2026-09-07): CI `34097318152` passed its compiled
end-to-end and installed-wheel jobs; its source jobs remain live. SDK
`34097320224` remains live, so no terminal SDK artifact result is claimed yet.
The earlier `34089520106` archive failure and cancelled runs remain dated
historical evidence.

## Final retained-image gates for the odd-default candidate

For candidate `236bcb54a7794669af1d139be466a51d91534fb1`, the default retained
gate passed all 58 migrated-pin artifacts plus manifest coverage: `59/59`
pytest, zero skips, in `412.03` seconds (`gpt6_release_retained_gate_20260907/default_RESULT.json`).
The authenticated historical retry passed `58/58` original pre-owner-v1
artifacts in `499.5` seconds using explicit `--research-unsafe`
(`original_retry/RESULT.json`). The initial original attempt remains preserved
as a failure at the first policy gate; it is not relabeled as a pass.

These are distinct reproduction paths. Seventeen default/original image
versions differ, and both manifests remain immutable. This closes the bounded
retained repack checks; it does not claim synthesis, SDK archive, CI, or
hardware qualification.

## Corrected native gate and replacement workflows, 2026-09-07

The complete native suite passes **270 tests, zero failures/errors/skips**, in 269.74 seconds using the source-identical odd-default binary `c00ad2b929f9714ddaeb1c0ca821592f67a8eef4309655da4592156779969f12` and overlay `7c8487f051e524274a0286c522f85290d4290890d520bafdd97e2d8b5cfa1777`. Evidence is retained in AG32-Docs `gpt6_release_native_corrected_20260907`. The previous CI native result remains 268 passed / two parity-only test failures; the corrected tests check actual bridge admission and routed endpoint semantics. A separate release-note self-link test failed and was repaired; release-note/document tests now pass 9/9.

CI `34097318152` and SDK `34097320224` ran at `dcaf28e`. CI compiled
end-to-end and installed-wheel jobs passed, while source jobs remain live; SDK
remains live. Earlier CI `34095135068` and SDK `34094652131` were cancelled
after the identified failures were corrected. Successful subjobs are partial
evidence, not complete workflow passes.

## Completed corrected CI — 2026-09-07

CI `34097318152` completed successfully at `dcaf28e713a33f58a6bd76315e48e135878f4c30`: all eight jobs passed. Python 3.9 reports 2,599 passed / 597 skipped; 3.11 and 3.12 each report 2,600 passed / 596 skipped; Windows reports 2,601 passed / 595 skipped. The compiled native end-to-end and three installed-wheel jobs also passed. Hardware-dependent skips remain scoped exclusions. This terminal result supersedes the earlier running checkpoint; SDK `34097320224` is a separate archive gate. Exact workflow metadata and full log are retained in AG32-Docs `gpt6_release_ci_complete_20260907`.
