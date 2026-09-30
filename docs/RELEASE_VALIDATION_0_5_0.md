# v0.5.0 validation

Evidence for the v0.5.0 release. The integrated candidate is `333e688`; the release
commit adds documentation only. Board results are from one AG32VF303CCT6 (L48) board,
SRAM configuration through a single controlled board client, with a passing reference
image between candidates and every recovery checked.

| Requirement | Evidence |
|---|---|
| Software | Full Python suite on `333e688`: 0 failures. Native-toolchain complement of every skipped case against the source-verified nextpnr build: 0 failures. Five Windows host checks pass. Cloud CI (Linux, Windows, macOS installed wheels) and the SDK bundle workflow pass. |
| Fresh default builds | All 18 corpus and holdout designs build with the default flow on `333e688`; an independent LUT and used-output audit of every image passes. |
| Default designs on hardware | 18/18 fresh images pass their rate contracts with reset-held controls, 19/19 references pass. |
| Memory holdouts, repeated resets | Two loads x 32 external reset releases each: fast RAM 64/64, slow RAM 64/64, FIFO 61/64, LFSR 61/64; source-matched vendor references 32/32. The FIFO and LFSR misses are explained below. |
| Wrong-image fixes | Five previously wrong default images were bisected on the board, by rerouting subsets of nets with every other route held, to one routing connection each; rerouting only that net made each pass. All five are refused, with 15 further vendor-unknown or mis-encoded connections. Rebuilt with the fix, the former failures and their seed variants pass. [Record](../qualification/afexe_absent_refusal_20260929.json). |
| Reset-release behaviour | The FIFO and LFSR holdouts use an asynchronous input pin directly as a synchronous reset. With a two-flop reset synchronizer added to the same RTL, the LFSR passed 128/128 and the FIFO 96/96 reset releases, against 61/64 and 93/96 without it. |
| Router-chosen LUT inputs | 38 designs built with the option on and off from the same source: 38/38 and 38/38 pass on the board; LUT truth-table and pin audits pass for all 76 images; with the option off, images are byte-identical to the previous flow. |
| Never-proven shape refusal | Stronger LFSR 0/32 -> 61/64 and both lowered-memory holdouts 0/32 -> 64/64 reset trials when introduced. [Record](../qualification/unproven_shape_refusal_20260929.json). |

## Not claimed

Build success is not silicon evidence for an untested design. A heartbeat checks only its
named oracle. The supported BRAM set, the L48 package, conservative timing without clock
skew, and the other limits in the [release notes](RELEASE_0_5_0.md) and
[supported scope](STATUS.md) bound every result above.
