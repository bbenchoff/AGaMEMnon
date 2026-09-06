# v0.4.0 release validation

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

The release job requires the wheel and both SDK jobs, archive SHA-256 checks,
tag/version agreement and an existing version-specific release-notes file.
Notes link to the exact tagged tree, not mutable main. Failed or merely queued
jobs do not qualify a release. Main and the tag are not advanced until the
candidate is reviewed; branch cleanup is separately recorded in
[the recoverable ref inventory](RELEASE_BRANCH_CLEANUP_0_4_0.md).
