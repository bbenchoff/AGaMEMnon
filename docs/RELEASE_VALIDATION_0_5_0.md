# v0.5.0 validation — publication pending

This is a release-preparation record. No v0.5.0 tag or published asset is claimed.
Predecessor evidence does not replace testing the final packaged candidate.

| Requirement | Evidence available | Remaining gate |
|---|---|---|
| Four exact BRAM source profiles | Four fresh builds at `1ee501b` reproduce raw and compressed image identities from the paired hardware matrix; 2,500 build artifacts verified. | Preserve these identities through the final installed SDK builds. Scope is fixed-address, single-observed-lane write/hold. |
| General FIFO correction | Three placement seeds pass controlled trials after selector corrections; a separate default-command build passes after memory retry ordering. | Repeat ordinary memory and FIFO cases on the combined release candidate. |
| Integrated software suite | Focused fixes have passing checks. Full native regression at `0a09f8f` is running. | Complete a green suite and review skips/failure scope. |
| Installed distribution | Installed-wheel checks at `0a09f8f` pass on Linux, Windows and macOS. Native SDK diagnostics are running. | Final versioned wheel and Windows/Linux archives, full release workflow, exact embedded-wheel and checksum verification. Diagnostic workflow alone cannot publish. |
| Default designs and hardware | Eighteen separate cases are prepared: 12 maintained designs and six holdouts. | Fresh builds, software/physical checks appropriate to each design, controlled hardware trials and recovery. |
| Vendor comparison | A prior paired core report and a broader capability inventory exist in the workbench. | Reconcile the final candidate with matched inputs, preserve vendor failures and untested categories, and publish the bounded comparison. |
| Publication | Runtime, project and bundle version metadata is being prepared for 0.5.0. | Final source identity, documentation, clean artifacts, tag and successful release publication. |

## Versioned packaging preparation

The publication-preparation branch aligns project, runtime and bundle versions at
0.5.0. Relevant SDK, image-plan, release-notes and bundle checks pass: 88 tests,
with two host-specific skips in that Windows run: MSYS `cygpath` is not on PATH,
and the POSIX quoting test does not apply there. The latter passes separately in WSL.
Two initially failing bundle fixtures still declared 0.4.0; they were updated to
the new release version, while deliberate wrong-version wheels remain rejected.

A local 0.5.0 wheel installed without network access in a new Windows virtual
environment, reported the correct version, and passed the installed data,
scaffolding and retained-bitstream smoke checks. Its SHA-256 is
`1d39a513665f68c13a457f17a554221d28543b2a7b503a0829f59145d56636ce`.
The real wheel also passes bundle preflight and the three version identities
agree. This is a packaging-preparation artifact, not the final published wheel;
it does not qualify native source compilation or new silicon behavior.

The public corrected BRAM evidence is
[`registered_bram_tmux9_source_selector_silicon.json`](../qualification/registered_bram_tmux9_source_selector_silicon.json).
Historical source and retained-checkpoint records stay unchanged. Raw vendor and
board evidence remains in the separate workbench.

Before publication, replace running/pending entries with terminal evidence and
update the installation instructions to the new tag. Preserve negative results
and explain any scope change; a selected passing subset is not the release gate.
