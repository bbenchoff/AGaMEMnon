# Native clock enable: supported scope and qualification — 2026-09-08

Native positive-polarity register clock enable is the default for ordinary
`build --uarch` on main after v0.4.0. No environment flags are needed. Use
`--no-native-clock-enable` to lower enables into ordinary register data logic.
Retained checkpoint and qualified-BRAM replay profiles preserve their historical
path automatically. The legacy Python architecture still uses data logic.
Build nextpnr with the supplied `build.sh`; it applies the required Viaduct
cluster-placement hook patch. Existing v0.4.0 release binaries are unchanged.

The supported composition uses line 0 and isolates native-enabled FFs from
ordinary or differently controlled FFs. Combined asynchronous controls and
line 1 remain outside this scope. Ordinary source builds use a native-enable
minimum group threshold of 8, LUT-to-multiple-FF broadcast preparation, and
native local-QIN preparation. These are placement/synthesis choices, not a
general capacity or speed claim.
If native registers are present and every attempt in the placement ladder
fails before routing, the default flow resynthesizes once with data-logic
enables. It preserves the native attempt logs and keeps both routing databases
separate. The explicit option skips the native attempt entirely. Timeouts,
unknown failures, safety refusals and timing failures do not trigger this retry.
The data-logic build still has to pass ordinary routing and emission checks.

## Placement repair

A control group must share a tile, but its register members need not occupy
slices 0 through N−1. The previous fixed cluster shape required exactly those
slices. Fixed MCU input reachability made those assignments illegal even where
other slots in the same tile were usable. This was not a three-control-set
hardware limit.

At the end of pre-placement preparation, the architecture now computes
per-member legal slots in each candidate tile and matches members to distinct
slots. Existing regions, fixed BELs, endpoint reachability and whole-placement
checks remain enforced. It also requires a feasible source location for the
enable-driving LUT: legal register slots alone did not ensure that the enable
net could reach its tile control sink. Callbacks use the resulting immutable
table rather than mutating bindings during parallel placement.

The existing assignment is preferred when legal. One matching is retained per
tile; this is not an exhaustive joint placement solver. Other cluster types use
the existing generic nextpnr implementation. New failures remain explicit
placement failures, with optional explained validity diagnostics.

## Encoding and compatibility

The tile-control encoder owns LogicTile control resources only. BRAM tiles
reuse some wire names and retain their existing resolver, including when the
native graph is enabled. Without that separation the branch intercepted
a retained BRAM enable route and refused an otherwise qualified image.

Legacy clock validation uses the canonical-LF identity already defined by its
registry. Raw-byte custody and output bindings retain their original identities.
This makes a Windows CRLF checkout reproduce the retained image without
accepting arbitrary changed inputs or updating any image pins.

## Bounded test composition

The initial complete ordinary-source release-strict build placed and routed on attempt
1 and reproduces raw image
`4959005cdc15d60483e425c66e8040054793740cc075cd004feee41248340771`.
Eight gated data bits use X16Y10 slices 0–7 on line 0. Their LUTs are identity
functions of write data, with no data-feedback hold mux; observing hold/resume
therefore tests the native enable path. Two read-word registers use line 0 at
X16Y12. Ordinary scratch bits occupy X16Y10 slices 8 and 10; the initial claim
that BYPASSEN safely exempts those neighbours was falsified on silicon.

The preregistered experiment updates gated data to A3, attempts complementary
5C and further 39/7E writes while disabled, then resumes with 5C. During the
disabled phase, exact scratch writes and readbacks of 2020/DFDF/2020 exercise
the two ordinary neighbours. A separate LFSR supplies phase-independent
liveness observations. Always-enabled, never-enabled and collateral scratch-
gating simulation mutations are rejected.

Before the subsequent tile-isolation experiment, the native regression passed
270 tests without skips. All 58 retained
images remain byte-identical (59 checks including manifest coverage); the
additional CRLF pack/tamper test and 103 focused tests also pass.

The first control-bracketed silicon session failed: both controls and the
reference passed, but every candidate AHB read returned the correct canary
A632, including addresses that should select scratch or gated data. The
read-word selection path therefore did not expose the intended registers.
This result does not establish their internal values or qualify native enable.
Final reset succeeded; custody was released; no flash writes occurred and
negative fences remain 74.

A second source build used explicit ordinary DFF read-word observers. The
observer and remote LFSR then worked, while native data read zero and the two
same-tile scratch bits failed. A diagnostic reversal of ten BYPASSEN bits
restored native update A3, all holds A3 and resume5C, but the scratch bits still
failed. Every session passed both controls and its retained reference; none
passed the full candidate contract. BYPASSEN alone is therefore not an
established ordinary-register exemption, and its earlier semantic claim is
withdrawn.

The native emitter clears BYPASSEN for native identity-LUT FFs.
Selecting the unused line for the ordinary neighbours, with either BYPASSEN
value, did not repair scratch. An explicit constant-source intervention also
failed. The physical meaning of these combined modes remains unresolved.

A fresh source fixture separates native and scratch input lanes within the
existing 16-bit input footprint. Its unrestricted placement put the ordinary
write-pending register beside the native bank; that image delivered no writes.
This does not establish a hardware prohibition on mixed tiles. The supported
path now conservatively excludes ordinary and differently controlled FFs from
a native-enable tile, in both placement and emission checks. Combinational LUTs
remain allowed. This is an admission restriction pending qualification of mixed
sequential modes.

The same source builds with that restriction: native data occupies X17Y10
slices 0 through 7, with all ordinary FFs outside the tile. Image
`a91f125a9e091dddbee995c6b82e309d227b2a968eac25db7967f4fe536d9710`
passed its composition and MCU read-lane audits, then passed the full silicon
contract three times. Both bracketing controls and the retained reference passed;
an independent audit re-parsed the raw readbacks and accepted the result. Final
reset completed and custody was released, with zero flash or option writes.
This witnesses the bounded isolated-tile composition, including native
update/hold/resume and ordinary scratch updates and LFSR activity elsewhere.
It does not qualify arbitrary mixed tiles. The owner approved this bounded
capability as the default on main on 2026-09-08; no new release was requested.
Negative fences remain **74 before, 74 after**.

The first three routing attempts exceeded their explicit 20-second budgets;
seed 4 completed. `build --uarch --attempt-timeout SECONDS` optionally bounds
each place-and-route subprocess so the existing retry ladder can continue.
A timeout is incomplete work and cannot be accepted as a routed image. The
default remains unlimited. With `AGAMEMNON_ATTEMPT_TRACE_DIR` set, native logs
are written during each attempt, including attempts terminated by the budget.
This controls execution time; it does not repair routing congestion or qualify
the reported timing model.

Vendor comparison artifacts and board orchestration remain in the private
evidence repository.

## Remaining boundaries

### Resource measurements after default promotion

A paired ordinary-source check at main `25ac0b2` compared the default with
`--no-native-clock-enable`, using the same binary and deterministic seed ladder.
It found no slice-count saving in the four sampled workloads:

| Workload | Slices, data logic → native | Result |
| --- | --- | --- |
| regbank16 | 68 → 69 packed | Data logic builds; native placement fails with two enabled read-word registers |
| addsub16 | 162 → 162 packed | Both bounded runs time out; neither uses native FFs |
| util20 | 442 → 442 placed | Both build across102 tiles; neither uses native FFs |
| enable qualification control | 69 → 69 placed | Both build; native uses16 tiles versus18 |

The enable control's reported Fmax changed from113.68 to111.12MHz. These are
model estimates, not measured silicon speed. The two-tile placement reduction
does not establish a general capacity increase. This measurement predates the
automatic placement fallback described above. `--no-native-clock-enable` still
avoids spending the native placement ladder on this regbank16 source. No
workload was modified to produce a favorable comparison.

The subsequent fallback regression recovers regbank16 after its 28 native
placement failures, with no carry fallback: 68 slices in 16 tiles and image
`710927189259f78b0d10806d54b2af7b3b7750e97ebaa0496caec2e4876a9bfb`,
byte-identical to the explicit data-logic build and retained passing reference.
The eight-register native control still reproduces its qualified `a91f125a…`
image. This restores build compatibility; it is not an area or speed improvement.

### Computed data LUTs: measured packing benefit

The [XOR3 example](../examples/native-clock-enable-xor3/README.md) exercises
eight reset-free enabled registers whose data depends on three inputs per bit.
Both ordinary-source versions route and emit. Data logic uses 77 slices;
native enable uses 69, saving eight slices (10.4%) with 44 registers in either
version. All eight native registers use `LUT_COMPUTE_TO_FF`: their three-input
data LUT and FF share a slice, with no external hold-feedback LUT. Named
feedback-buffer count is zero in both versions; this saving is hold-logic
removal and LUT/FF packing, not removal of the direct-D workaround.
Occupied tiles increased from 17 to 19 (4.53 to 3.63 slices per occupied tile),
so tile isolation and placement remain separate capacity limitations.

The native image
`dc082c5bce1c7062ed5322de67b483595a3406bc939f8af2fd872077960f1234`
passed three control-first silicon runs. Each checks every input byte with an
enabled update and disabled hold (512 checks), then the eight update/resume,
scratch and liveness check groups. Always-enabled, never-enabled, scratch-
blocked, identity-data and missing-input mutants are rejected in simulation.
Both bracketing controls and the retained reference passed; an independent
auditor accepted the raw logs. Final reset and custody release completed with
zero flash or option writes. Fences remain 74.

This extends the witnessed input composition from identity LUTs to computed
three-input XOR LUTs at X17Y10 slices 0–7, still isolated and using line 0 with
BYPASSEN clear. Reported model Fmax changed from 109.49 to 115.43 MHz; the
silicon runs used 10 MHz and do not qualify a speed increase. Other enable
populations may have different packing and placement outcomes.

### Remaining qualification limits

Line 1, synchronous shared controls, asynchronous control admission, arbitrary
coordinates, combined modes, timing closure and general placement capacity are
not qualified by this fixture. The unexplained vendor BYPASSEN comparison stays
unexplained. A passing bounded contract does not close an unrelated silicon
fence or establish support outside the enforced isolated line-0 composition.

## Native SRST candidate selection

Native synchronous-reset recovery is evaluated as a bounded build choice for
ordinary source builds. The CLI completes both recovered and legacy-native
candidates, then selects
the lower final routed `GENERIC_SLICE` count; equal counts retain legacy. This
uses completed routed results because pre-pack counts do not account for
selective enable lowering or placement effects. It can therefore add one full
candidate build's runtime.

`<output>.native-srst-selection.json` records each routed or exhausted
candidate, its final slice count and routed hash, the selected mapping, and
the selected image hash. `AGRV2K_SHARED_CONTROL_SRST_RECOVERY=0` or `=1`
selects reset lowering without automatic comparison. These explicit settings
leave the other optimization defaults active, allowing an SRST-only A/B.
To reproduce the full historical profile explicitly, also set
`AGRV2K_SHARED_CONTROL_MINCE=4`, `AGRV2K_LUT_FF_BROADCAST=0`, and
`AGRV2K_NATIVE_ENABLE_LOCAL_QIN=0`. Direct synthesis and project
builds default to legacy (`0`); no-native builds keep their existing path.
The recovered candidate uses ordinary CLI defaults
`AGRV2K_SHARED_CONTROL_MINCE=8`, `AGRV2K_LUT_FF_BROADCAST=1`, and
`AGRV2K_NATIVE_ENABLE_LOCAL_QIN=1`; the legacy candidate retains its
historical missing-only defaults of 4, 0, and 0. Explicit user values override
both profiles.
`AGRV2K_SHARED_CONTROL_MINCE` remains a positive native-enable group threshold.
An explicit zero-assignment placement certificate can selectively lower only
the infeasible enable group while retaining successful native groups.

The bounded SRST priority fixtures have silicon results: reset-first (priority
0) measured soft/native 3/3 PASS at 78/73 slices, and enable-first (priority
1) measured soft/native 3/3 PASS at 78/72 slices. Each native arm used exactly
the eight target registers as native enables. These results cover only those
priority/value contracts and isolated line 0 fixture contracts.

This selection preserves a lower-cost mapping; it does not claim a general
routing, timing, ABC9, or silicon improvement. The priority fixtures do not
qualify arbitrary synchronous control compositions.
