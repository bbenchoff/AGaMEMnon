# HIL campaign work lists

`agamemnon hil-campaign WORKLIST --root ARTIFACT_ROOT` turns a bounded silicon
diagnosis list into a deterministic, hash-bound execution plan. A work list
names its complete design denominator and carries exactly one or two candidate
interventions per design. Every ready job binds one observer firmware, one
control image, every candidate image, and exact masked observation outcomes.
The plan always orders them as control, candidate(s), then the identical
control recovery image.

Every job also hash-binds at least one diagnosis/evidence artifact. This keeps
the candidate queue attached to the exact evidence that motivated it rather
than to a mutable prose label.

Planning is desk-only. A work list can retain a blocked job, but it must say
why and cannot carry execution steps. `--require-ready` converts any such job
into a fatal gate. Present artifacts are checked even on blocked jobs: paths
must be portable and stay below the supplied root, sizes must match, fabric
images must be exactly 99,944 bytes, and every SHA-256 must match.

The three producer labels keep unlike evidence separate:

- `mcu-ahb` uses an SRAM observer to stimulate or read the configured fabric;
- `fabric-ahb-master` is reserved for the bounded read-master path and remains
  blocked until its hard request boundary can be independently driven;
- `external-fixture` records observations that require pad or protocol
  apparatus in addition to the AG32 DAP.

The current FCB transport can replace exact images without reloading its SRAM
firmware. A campaign-specific board adapter consumes one ready job, captures
the declared words after every image, and passes them to
`agamemnon.hil_campaign.run_ready_job`. The public classifier returns one named
outcome, `AMBIGUOUS`, or `UNCLASSIFIED`, and refuses a classified run unless the
final control returns to the same unambiguous class as the first control.

FCB acceptance is only configuration evidence. A classified intervention is
only the bounded discriminator named in its work list. Neither event by itself
establishes a root cause, a repair, parity, or a release-surface promotion.
