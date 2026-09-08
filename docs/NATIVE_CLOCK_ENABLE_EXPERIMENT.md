# Native clock enable: supported scope and qualification — 2026-09-08

Native positive-polarity register clock enable is the default for ordinary
`build --uarch` on main after v0.4.0. No environment flags are needed. Use
`--no-native-clock-enable` to lower enables into ordinary register data logic.
Retained checkpoint and qualified-BRAM replay profiles preserve their historical
path automatically. The legacy Python architecture still uses data logic.
Build nextpnr with the supplied `build.sh`; it applies the required Viaduct
cluster-placement hook patch. Existing v0.4.0 release binaries are unchanged.

The supported composition uses line 0 and isolates native-enabled FFs from
ordinary or differently controlled FFs. Synchronous reset remains lowered to
data logic; combined asynchronous controls and line 1 remain outside this scope.
Placement can still fail under these restrictions; the explicit data-logic
option provides the previous implementation without weakening legality.

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

Line 1, synchronous shared controls, asynchronous control admission, arbitrary
coordinates, combined modes, timing closure and general placement capacity are
not qualified by this fixture. The unexplained vendor BYPASSEN comparison stays
unexplained. A passing bounded contract does not close an unrelated silicon
fence or establish support outside the enforced isolated line-0 composition.
