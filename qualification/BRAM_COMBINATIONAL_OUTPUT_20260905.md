# Combinational BRAM-source output selection — September 5, 2026

BRAM corridor packing can annotate a source slice with AGRV2K_OMUX_SEL=2.
That is a register-output selection, not permission to replace a live LUT F
output when FF_USED=0. The emitter now ignores that hint for combinational
cells. Registered sources retain the explicit-selection requirement; existing
direct-D and left-output compatibility policy is unchanged.

The native saved-path lookup repair is separately committed at `35c8188`.
On the unchanged strict graph, an explicit post-synthesis two-stage identity
buffer composition makes ROM256 route. Its two terminal identity cells expose
the output-selection error: the annotated image fails three full read tests,
with 186 erroneous visits each. Clearing just two non-CRC selection bits gives
three complete passes, checking 1,024 reads per repetition. Public32 controls
pass; zero-content negatives produce their exact independently predicted
failures. Ordinary packing with the corrected emitter reproduces the passing
bytes without removing annotations. INIT restoration and post-synthesis
buffering remain research-only; initialized-read admission is not widened.

Image SHA256: `2d83259934e3c94d617d78c65bd2295ea5da202330c38af7927a231579e8fde7`.

The changed emitter initially trips the existing exact-output hash guard for
three retained SERV artifacts. Old-image controls and three fresh repetitions
of each changed image all pass reset-gated checks on L48, using GP4/PIN_10 reset
and GP12/PIN_25 observation. Signature checks observe high at both sample
intervals; heartbeat checks observe both levels and positive edge counts;
blinky observes both levels. Every run observes low under reset before and
after release. Public32 passes first; FCB and loader sentinels are checked.
Pico returns to ALLIN, the board is reset and the lock released. No flash writes
or Pico reflash. This is not full ISA, timing closure or arbitrary RTL support.

The [migration ledger](serv_f_output_requalification_20260905.json) binds the
old/new images and fresh evidence. Historical September 4 records are retained;
the current SERV compliance record supersedes rather than overwrites them.
Only the three exact-image pins change. Routed identities, clock environments
and legacy clock-leaf quarantine do not change. The packaged runtime registry
is regenerated from the same 58-artifact manifest, with both identity checks
and output-hash refusal retained.

Raw research evidence is pinned at AG32-Docs commit
`51c1dffe732a24a639ffae15e34f113df88a40d8`, under
`tools/vendor_parity/gpt6_bram256_buffer_outputs_20260905`,
`gpt6_bram256_ordinary_f_emitter_20260905` and
`gpt6_serv_f_output_silicon_20260905`. No vendor material is copied here.

Focused encoder tests pass 172. The broader migration run passes 322 checks,
including all 58 retained normal-CLI image repacks; two stale SDK archive and
compressed-image expectations initially fail. Those are corrected to the
witnessed bytes and both reruns pass (6.09 seconds). The initial run is retained
as `migration_regression.xml`, not relabeled green. The fingerprint tripwire
separately rebuilds its 50 included artifacts successfully before refusing the
stale fingerprint as designed (211.00 seconds); only then is the fingerprint
updated. Its green check and the eight excluded-policy repacks are covered by
the broader run. Evidence is in the research `gpt6_serv_f_output_20260905` tree.

Earlier full-suite results do not qualify this new change. General full-depth
ROM8192 allocation, automatic buffering, other widths/sites/ports and
write/collision semantics remain open.

### Independent round-trip validator follow-up

The full Windows suite on clean `3512254` records 2,218 passes, 470 skips and
three failures (1,443.13 seconds). All three are SERV round trips: the independent
OMUX validator retained an older rule forcing one for any explicit BRAM output
hint, including inactive-register F owners. It rejected 12/16/16 selector zeros
in the already requalified images. The original failed report is preserved in
AG32-Docs commit `bc3b8b9c7fac558b74769426bdffecdc599cb03e`.

The validator now keeps its independently reconstructed F/Q value while still
requiring the correct BRAM mode marker and selector index. It does not consult
the emitter or exclude these cells from exact-bit comparison. New fixtures cover
all three output indices and zero/identity/one contents, with bit-flipped
negatives, registered-output positives, and invalid mode/selector/Q refusals.
The red run records nine failures and six passes before the correction.
No emitter, chipdb, image hash, qualification admission or runtime data changes
are part of this validator follow-up.

The corrected validator's complete follow-up passes **84 tests** in 350.08
seconds: all 58 retained-image round trips, the manifest guard, ten existing
validator tests and fifteen new positive/negative fixtures. Every retained
image still matches its existing pin. This resolves the three full-run
failures; it does not relabel that original full run or claim a new complete
suite on the follow-up commit.
