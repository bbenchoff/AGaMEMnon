# Long carry corridor correction

The old `LEGACY_33` template placed a seeded chain at X20Y11, then X20Y12,
then X20Y10. Its upward and skipped-row links do not implement the intended
32-bit counter. A strict native build adding 131071 on each 10 MHz clock
produces about 5 MHz at count[31], rather than the expected 305.17 Hz.

The corrected `X20_DOWNWARD_33` template uses consecutive downward tiles:
X20Y12_SLICE0..15, X20Y11_SLICE0..15, then X20Y10_SLICE0. Native placement
keeps the root at X20Y12_SLICE0. Direct packing independently rejects the
old topology and translated or skipped-row versions of the new template.
Rebuild old long-carry routed artifacts from RTL.

The 10–25-site native family also stays rooted at X20Y12_SLICE0; the new
second seam does not authorize translating it to rows 11/10. Direct packing
keeps the exact retained 25-site X10Y4-to-X10Y3 counter footprint readable,
without admitting other translations or prefixes of that compatibility case.

The older 33-site qualification checked only that two output lanes varied.
That observation did not distinguish the incorrect topology from a working
counter. Its evidence remains in the ledger with a correction; it no longer
authorizes the old seams. Existing shorter retained images remain subject
to their byte-identity regression.

## Reproduction

Use this checkout and a native nextpnr binary rebuilt from its agrv2k source:

```text
python -m agamemnon.cli build qualification/counter32_carry_rate.v --uarch --hard-carry --release-strict --no-native-clock-enable --freq 10 --pcf qualification/counter32_carry_rate_L48.pcf -o counter131071.bin
python -m agamemnon.cli build qualification/counter32_carry_rate_step65539.v --uarch --hard-carry --release-strict --no-native-clock-enable --freq 10 --pcf qualification/counter32_carry_rate_L48.pcf -o counter65539.bin
```

Both designs retain 32 registered arithmetic stages plus one carry seed.
They use ordinary routed D/VCC and ordinary Q-to-B feedback. No experimental
unselected-input or A-feedback mode is involved.

| Increment per clock | Expected PIN17 frequency at 10 MHz | Native image, repeated 1 s windows |
|---|---:|---:|
| 131071 | 305.173453 Hz | 305–306 Hz |
| 65539 | 152.594876 Hz | 152–153 Hz |

Expected frequency is `clock_hz * increment / 2**32`. Unknown initial
counter state changes phase, not the steady rate. SRAM-only trials used
both input biases on the external observer and restored the board after
each run. An independently working 17-bit counter bracketed the initial
comparison. The source-fresh corrected images passed three alternating
pairs; image and source identities are recorded in
[`carry_evidence.jsonl`](../qualification/carry_evidence.jsonl).

These are rate witnesses for this footprint, these increments and 10 MHz.
They do not qualify arbitrary 32-bit arithmetic, every state of the counter,
other columns, other long-chain roots, or timing limits. The accumulator
capacity and routing work remains separate.
