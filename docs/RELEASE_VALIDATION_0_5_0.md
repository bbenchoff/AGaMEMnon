# v0.5.0 validation — publication pending

This is a release-preparation record. No v0.5.0 tag or published asset is claimed.
Predecessor evidence does not replace testing the final packaged candidate.

| Requirement | Evidence available | Remaining gate |
|---|---|---|
| Four exact BRAM source profiles | Four fresh builds at `1ee501b` reproduce raw and compressed image identities from the paired hardware matrix; 2,500 build artifacts verified. | Preserve these identities through the final installed SDK builds. Scope is fixed-address, single-observed-lane write/hold. |
| Fresh completed-read BRAM checks | Register-fanout repair is on public main at `8b7b96f`. Four fresh builds at `8fe0699` are reproduced byte-for-byte by encoder `4e122cc`. OUTREG1, SDP4 and x18 pass twice; x1 OUTREG0 fails twice. All eight vendor controls, 17 references and 33 recoveries pass. | Resolve OUTREG0 and qualify additional modes, sites and ordinary inferred memories. The isolated predecessor main still fences OUTREG1; hardware capability admission belongs to the pending integration. |
| General FIFO correction | Three placement seeds and the ordinary memory retry correction have passing trials. A later direct-reset comparison still fails once in 64 releases; sampled alternatives pass their 64 trials. | Explain the retained failure and qualify the resulting general correction. Sampled-reset passes alone do not close it. |
| Integrated software suite | The full local `2daf606` gate completed with 4,220 passes, 54 skips and one native placer segfault; four targeted reruns did not reproduce it. Register-fanout integration passes 180 focused checks; its earlier encoder also passes all 60 retained-pack checks. | Resolve the native crash and complete the final integrated gate and remaining platform coverage. Focused passing checks do not supersede the full-gate failure. |
| Installed distribution | At `eb49aff`, installed-wheel checks pass on Linux, Windows and macOS; Windows/Linux nonpublishing SDK diagnostics pass offline installation, MCU/FPGA builds and the exact BRAM source smoke. | Regenerate final artifacts from the final source, verify the embedded wheel and checksums, then complete the publication workflow. Earlier diagnostic archives are not final release assets. |
| Default designs and hardware | All 18 default builds pass on `eb49aff`. Hardware passes 17 and fails the LFSR, with all 19 references passing. Later stronger LFSR and completed-read-round BRAM checks expose additional implementation-specific failures. | Resolve failures rather than treating the 17 passing activity oracles as complete qualification. Revalidate the final implementation and checker contracts. |
| Vendor comparison | All 18 sources/constraints are paired; 17 vendor builds pass and one fails. Of the 17 built vendor images, 13 pass the controlled observation and four fail. Stronger paired LFSR/BRAM comparisons have working vendor controls and failing open implementations. | Keep the original failures visible; do not treat the adapted vendor flow as universally correct or dismiss modes with fresh valid vendor passes. Expand the bounded comparison toward the capability matrix. |
| Publication | Runtime, project and bundle version metadata is being prepared for 0.5.0. | Final source identity, documentation, clean artifacts, tag and successful release publication. |

The frozen software evidence is bound to
[`eb49aff` CI](https://github.com/bbenchoff/AGaMEMnon/actions/runs/36242171631)
and [SDK diagnostics](https://github.com/bbenchoff/AGaMEMnon/actions/runs/36242172823).
The [current hardware summary](../qualification/release05_current_hardware_results.json)
records source-paired BRAM/LFSR results, retained alternatives and clock-only
interventions and the register-fanout repair. Independently validated fixes are
on public main through `8b7b96f`; their focused software gates do not publish or
qualify the larger feature stack.

## Versioned packaging preparation

The earlier publication-preparation candidate `3d68a57` aligns project, runtime
and bundle versions at 0.5.0. Relevant SDK, image-plan, release-notes and bundle checks pass: 88 tests,
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

This combined candidate incorporates those metadata changes on the regression
repairs through `477920c`. Its compiler package differs from that regression
candidate only in the version constant; final tests and artifacts must still bind
this candidate's complete source identity. The older wheel above is not its wheel.

A retained FIFO recheck produced an unexplained zero-frequency observation after
reset release. A later equal-count comparison reproduces one failure in 64
direct-reset releases and none in 64 for each sampled alternative. These results
do not establish a root cause or qualify arbitrary reset implementations.

The public corrected BRAM evidence is
[`registered_bram_tmux9_source_selector_silicon.json`](../qualification/registered_bram_tmux9_source_selector_silicon.json).
Historical source and retained-checkpoint records stay unchanged. Raw vendor and
board evidence remains in the separate workbench.

Before publication, replace running/pending entries with terminal evidence and
update the installation instructions to the new tag. Preserve negative results
and explain any scope change; a selected passing subset is not the release gate.
