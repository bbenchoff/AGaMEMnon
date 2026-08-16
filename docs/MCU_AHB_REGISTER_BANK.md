# MCU External AHB register bank

Status: the response-source allocation gap is closed. The release backend now
matches response drivers globally and negotiates the full `HRDATA[31:0]`,
`HREADYOUT`, and `HRESP` corridor set without router1 legality failures. The
combinational constant-ready/OKAY endpoint builds with strict bitgen and is
silicon-qualified on L48. Pure-open `MCU_BUS_CLOCK` delivery now runs an
explicit three-bit counter at the exact qualified X14Y11 slice4/6/7 direct-D
sites and exposes all eight states. A separate 16-bit LFSR produces 500
distinct states and advances exactly once per undivided MTIME tick (a 1:1
ratio; the absolute rate long printed as 10 MHz is an open question -- see
[MCU_CLOCKS.md](MCU_CLOCKS.md#external-ahb-bus-clock)).
An explicit GPIO4.1-fed synchronous reset also holds that LFSR at zero and
re-arms it. The default SDK profile now strictly replays one exact L48 map
that composes canonical ID32 `0x4147414d` with zero-extended held scratch16,
counter3, W1C1, and GPIO reset. The narrower public16 ID8 map is retained as a
separate qualified profile.
The older complete-byte image remains retained separately and qualifies exact
32-bit zero-extended reads and fail-closed non-SINGLE behavior on its own
narrower storage composition. A separate
immutable-ID endpoint qualifies exactly one controlled wait for every single
aligned word read or ignored write. A third strict image composes one
controlled write wait with all eight scratch lanes. Exact 32-bit reads and
aligned byte/halfword semantics are also qualified. SINGLE is the supported
transfer boundary; all seven nonzero HBURST encodings fail closed in the
public core with HRESP and no state mutation. Non-SINGLE acceptance is
RETIRED by `2026-08-05-l48-register-bank-nonsingle-bursts-retired`. Misaligned
CPU accesses fault deterministically in the hard core before reaching the
fabric (mcause 5/7), so the reachable transfer surface is exactly the aligned
one. Hard `MCU_RESETN` control is decoded (`SYS->RST_CNTL` at `0x03000004`;
bit 2 `FCB_RST_DIS` exempts the fabric from MCU resets, default 0) and was
exercised by the board operator on 2026-08-11 under the documented BOOT0
protocol with a reported-working result; no machine-captured observations
were retained from that run, so hard `MCU_RESETN` remains operator-attested
and outside the silicon-qualified claim pending one captured run.
Deterministic MCU exceptions
from fabric `HRESP` are RETIRED on the attached L48: the exact two-cycle signal
and wait were electrically active, but the MCU raised zero load or store access
traps and the response phase crossed into the following transfer.
Isolated HADDR[5] and HADDR[3] logic-ingress oracles each pass 256/256
addresses; retained HADDR[4]^HADDR[5] evidence now also qualifies HADDR[4].
The paired HWRITE/HTRANS1 X14Y12 slice0 qualifier footprint and working
HWDATA[0], HWDATA[1], HWDATA[2], HWDATA[3], HWDATA[4], HWDATA[5], HWDATA[6], and HWDATA[7]
registered consumer paths are
represented. A bounded pure-open byte-wide posted-storage image routes and passes all
256 values, immediate write/read, back-to-back newest-write forwarding, and
HADDR2-tagged offset isolation. Later bounded images integrate ID/scratch, a
read-only lower-three-bit counter at offset eight, and a one-bit W1C status at
offset C, then add synchronous GPIO-fed reset to the complete bank.

`agamemnon/rtl/mcu_ahb_register_bank.v` contains two layers:

- `agamemnon_ahb_register_bank`, a vendor-independent AHB-Lite protocol core;
- `agamemnon_mcu_ahb_register_bank`, which binds that core to the recovered
  typed AG32 External AHB port.

The vendor-independent protocol core's default register map is:

| Offset | Access | Register | Behavior |
|---:|:---:|---|---|
| `0x00` | RO | ID | Returns `0x4147414d` (`AGAM`) |
| `0x04` | RW | Scratch | Supports aligned byte, halfword, and word writes |
| `0x08` | RO | Counter | Increments on every bus clock after reset |
| `0x0c` | W1C | Status | Latches `STATUS_SET`; writing one clears a bit |

Unsupported sizes, misaligned accesses, out-of-range addresses, and writes to
read-only registers complete with `HRESP=1` in the vendor-independent protocol
model. `WAIT_STATES` inserts a bounded number of response cycles. The corrected
slave model decrements this internal counter independently of `HREADY`; gating
it with `HREADY` would deadlock because the slave itself holds `HREADYOUT` low
during the wait. That simulation behavior is not a silicon claim that AG32's
MCU turns hard-port `HRESP` into an architectural access fault.

Generate the matching firmware header with:

```powershell
python -m agamemnon.mcu_register_bank `
  --base 0x60000000 --output fabric_register_bank.h
```

The checked-in default is
`examples/riscv_mcu/fabric_register_bank.h`. RTL regressions cover byte,
halfword, and word writes, reads, inserted waits, back-to-back writes,
misalignment/range/read-only errors, reset, the free-running counter, and W1C
status behavior.

The current AG32 hard-port wrapper deliberately has a narrower boundary than
the protocol core:

- `DATA_BITS=8`: writable Scratch/Status data uses `HWDATA[7:0]`; upper bits
  read as zero and upper write bits are ignored;
- aligned byte and halfword access is enabled for the qualified low writable
  byte; address-shifted upper-byte/upper-half writes are masked out;
- the wrapper observes address bits `[5:0]` for its near-window decode; unseen
  address bits are filled from `BASE_ADDR`, so they alias rather than proving a
  wider runtime decode; and
- reset is synchronous because the AGRV2K slice model has no qualified
  asynchronous set/reset lowering.

These restrictions are fail-closed implementation boundaries, not statements
about the theoretical hard AHB port.

The silicon error-fault claim has a stronger boundary. Records
`2026-08-05-l48-error-single-cycle-negative` and
`2026-08-05-l48-error-constant-high-negative` raised no exceptions. The final
record `2026-08-05-l48-error-two-cycle-f2-retired` reused the exact qualified
X14Y11 OMUX20 HREADYOUT route and drove HRESP from OMUX15. Across 256 reads it
added 511 MTIME ticks and returned the `0xffffff4f` response-phase witness;
across 256 fenced stores it added 297 ticks. The independently validated trap
handler still counted zero load and zero store access traps, and a response
phase contaminated the next ID check. The route is live, but using HRESP as a
deterministic MCU fault mechanism is RETIRED. The exact F2 replay option remains
experimental and there is no release support claim for this behavior.

Record `2026-08-05-l48-combined-bank-one-wait-seven-bit-pure-open` closes a
bounded writable-wait composition without weakening the lane6 negative. The
strict image retains the qualified response controller and seven unaffected
scratch lanes, but ties scratch bit 6 to registered zero at X14Y12 slice15.
All 256 writes returned `value & 0xbf`; the observed OR/AND masks were `0xbf`
and zero, proving every supported bit toggled while lane6 stayed zero. Another
128 back-to-back write pairs passed, ID remained `0x4d`, W1C set/clear and all
eight counter states passed, and GPIO reset cleared every state. The 256-write
loop took 3615 cycles versus 1037 for SRAM, a 2578-cycle delta. Strict bitgen
used 551 data PIPs, 537 recovered mappings, and no predicted, legacy, or
unmapped selectors. This is a seven-bit, aligned-word, write-wait claim;
reads remain zero-wait, and a full-byte waited bank, bursts, and byte/halfword
semantics remain outside the boundary.

The next full-byte discriminator recovered an exact, strictly encoded early
commit corridor from the qualified X14Y12 slice1 token to the X14Y4 high
commit buffer. Advancing lanes 2, 3, 4, and 6 together retained reset and the
2082-cycle wait delta, but `0xa5` read back `0xc1` and the later `0x3c`
checkpoint read zero. Record
`2026-08-05-l48-combined-bank-wait-early-high-commit-negative` therefore
retires that phase architecture unchanged. It is a coupled retained negative,
not a dead-PIP or route-conduction claim.

A lane6-only follow-on routed the already-qualified scratch commit-stage F
output to the exact lane6 commit input over three strict, conflict-free PIPs.
It retained reset and the 2082-cycle wait delta, but both lane6-clear
discriminants acquired bit 6: `0xa5` returned `0xe5` and `0x3c` returned
`0x7c`. Record
`2026-08-05-l48-combined-bank-wait-lane6-commit-f-negative` retains this
coupled negative. The exact route remains live; qualified combinational commit
phase alone is exculpated as the repair, and this topology must not be rerun
unchanged.

Extending the response stall through the registered commit-root cycle was also
an exact no-effect discriminator. Commit-root Q reached unused wait-stage I3
over three strict PIPs, and `0xCCDD` held HREADYOUT low for pending or commit.
The 256-write delta rose from 2082 to 2087 cycles, but the original signature
repeated exactly: `0xa5` returned `0xe5`, while the later `0x3c` was exact.
Record `2026-08-05-l48-combined-bank-wait-two-cycle-negative` retains this
timing negative and exculpates response-release duration for that signature.
The topology must not be extended or rerun unchanged.

The next state-equation discriminator restored lane6 own-Q feedback to the
pure-open-qualified I3 path through OMUX46, moved reset to I2 through free
RMUX16, and used exact `0x0B08` for reset-zero, commit/data, and hold. Reset,
the 2082-cycle wait delta, and the original `0xe5`/exact-`0x3c` signature all
remained unchanged. Record
`2026-08-05-l48-combined-bank-wait-lane6-ownq-pin-negative` retains this
negative and exculpates own-Q pin placement. It is not a dead-PIP claim and
must not be rerun unchanged.

An independent read witness then separated state from readback. HRDATA7 moved
onto its previously qualified RMUX56 ingress, and raw scratch6 Q reached
HRDATA8 over seven free strict PIPs while the ordinary HRDATA6 path remained
unchanged. Across all 256 values, bits 6 and 8 agreed in every case but both
had 127 expected-data errors: both were zero only at value 0 and one for
values 1–255. Reset cleared both. Record
`2026-08-05-l48-combined-bank-wait-lane6-q-witness` therefore exculpates the
ordinary class-mux read branch and localizes the retained failure to stored
lane6 state. This is a causal witness, not a full-byte support claim.

Replacing the implicated storage primitive did not change the signature.
Slice15 became a combinational HWDATA6 I0 identity, its F output reached a
separate X14Y12 slice6 reset-aware register over six free strict PIPs, and the
original read path was rerouted from that new Q. Reset, the 2082-cycle delta,
and `0xe5`/exact-`0x3c` all repeated. Record
`2026-08-05-l48-combined-bank-wait-lane6-separate-storage-negative` exculpates
both the slice15 Q primitive and replacement storage site. Comparing the
retained routes now isolates the changed HWDATA6 ingress corridor from the
qualified pure-open bank as the next causal boundary.

Restoring that exact ingress eliminated the sticky-high basic failure. One
HADDR2 leaf moved off RMUX25 over six strict PIPs, then HWDATA6 reused the
pure-open RMUX07/RMUX25/RMUX22 path. The basic oracle returned exact `0xa5`
and `0x3c` with the same 2082-cycle delta. Exhaustive promotion still found
3/256 sequential and 64/128 back-to-back errors, while OR/AND was `0xff`/zero
and ID, W1C, counter, wait timing, and reset passed. Record
`2026-08-05-l48-combined-bank-wait-qualified-hwdata6-route-partial-negative`
retains this partial negative. Three sequential errors are consistent with the
three bit6 transitions and point to a one-transfer lane6 commit lag; the exact
ingress must be retained while lane6 commit phase changes.

Record `2026-08-05-l48-combined-bank-one-wait-complete-byte` closes the full
eight-bit waited-bank boundary. The exact pure-open-qualified HWDATA6 ingress
and HADDR2 relocation remain unchanged; only lane6 commit advances from the
scratch commit-stage combinational F. The result passed all 256 values and 128
back-to-back pairs with OR/AND masks `0xff`/`0x00` and zero errors. ID `0x4d`,
W1C set/clear, all counter states, GPIO reset/re-arm, and one-write-wait timing
remained correct; the waited loop added 2587 MTIME ticks over SRAM. All 596
routed PIPs were strict and conflict-free; bitgen used 549 data PIPs, 535
recovered mappings, and no predicted, legacy, or unmapped selectors. This
qualifies aligned single-word writes with one controlled wait and zero-wait
reads. The existing HRDATA[15:8] zero routes still require recomposition with
this complete-byte route; HRDATA[31:16], byte/halfword access semantics,
bursts, and hard `MCU_RESETN` remain outside the claim.

Record `2026-08-05-l48-wait8-hrdata8-explicit-zero` begins upper-zero
recomposition on that exact complete-byte route. It preserves the qualified
HWDATA6 ingress and commit-stage-F closure, relocates HRDATA7 onto its already
qualified RMUX56 exit, and drives HRDATA8 from the existing explicit GND LUT.
The complete-byte regression remains green. Across 256 halfword cases, 256
word cases, and 128 mixed pairs, every low-nine-bit result was exact; halfword
OR/AND was `0xfeff`/`0xfe00` and word OR/AND was
`0xfffffeff`/`0xfffffe00`. HRDATA[15:9] and HRDATA[31:16] remain undriven, so
exact halfword/word reads remain unsupported pending the remaining zero lanes.

Record `2026-08-05-l48-wait8-hrdata9-explicit-zero` adds the previously
qualified free GND branch through RMUX13. The complete-byte regression remains
green, and HRDATA9 stayed zero across 256 halfword, 256 word, and 128 mixed
cases. Offline binding is exact through HRDATA9 and strict bitgen used zero
unmapped or guessed selectors. HRDATA[15:10] and HRDATA[31:16] remain open.

Record `2026-08-05-l48-wait8-hrdata10-explicit-zero` adds the one-hop RMUX72
GND branch. The full-byte regression remains green and HRDATA10 stayed zero
across all 256 halfword, 256 word, and 128 mixed cases. HRDATA[15:11] and
HRDATA[31:16] remain open.

Record `2026-08-05-l48-wait8-hrdata11-explicit-zero` adds the free RMUX48 GND
branch without moving any prior route. HRDATA11 stayed zero across all tested
halfword, word, and mixed cases and the complete-byte regression remains green.
HRDATA[15:12] and HRDATA[31:16] remain open.

Record `2026-08-05-l48-wait8-hrdata12-explicit-gnd` replaces the old
seven-bit-only scratch6 constant with a real GND source. One scratch6 consumer
moves to a three-hop strict alternative, freeing RMUX25 for a new INIT-zero LUT
at X14Y10 slice6 to reach HRDATA12. Full-byte storage and HRDATA12 zero both
pass silicon; HRDATA[15:13] and HRDATA[31:16] remain open.

Record `2026-08-05-l48-wait8-hrdata13-explicit-zero` adds the free RMUX20 GND
branch from the already-owned X16Y11 RMUX20 wire without moving a prior route.
HRDATA13 stayed zero across all tested halfword, word, and mixed cases and the
complete-byte regression remains green. HRDATA[15:14] and HRDATA[31:16]
remain open.

Record `2026-08-05-l48-wait8-hrdata14-explicit-zero` branches from the
already-owned X19Y9 GND RMUX15 wire through free X20Y9 RMUX69, X20Y11 RMUX86,
X18Y11 RMUX56, and X14Y11 RMUX26 without moving any prior route; bit 14 stayed
zero across all halfword, word, and mixed cases. A first HRDATA15 candidate is
a retained coupled negative
(`2026-08-05-l48-wait8-hrdata15-imux-turnaround-negative`): the composition was
conflict-free with exact selectors, but the X14Y8 IMUX17-to-RMUX69 turnaround
is not a transparent constant route in this context and must not be reused as
a generic GND path. Record `2026-08-05-l48-wait8-hrdata15-explicit-zero` then
closes HRDATA[15:8] from the owned X20Y9 RMUX69 GND wire over five free
route-only edges, without treating live scratch6 as a constant.

Record `2026-08-05-l48-wait8-hrdata16-explicit-zero` opens the upper word with
only the exact RMUX20-to-BBMUXE03 ingress and sink edges from an owned GND
wire, and `2026-08-05-l48-wait8-hrdata17-explicit-zero` follows from the owned
X15Y11 RMUX08 GND wire over four free route-only edges. Record
`2026-08-05-l48-wait8-hrdata18-31-route-only-group` qualifies a 12-lane
explicit-zero group in one image: conflict-aware route-only search found
strict paths for HRDATA18, 19, 21–26, and 28–31 (combined mask `0xf7ec0000`),
while HRDATA20 and HRDATA27 had no free route-only path and were excluded
rather than guessed. Record `2026-08-05-l48-wait8-word32-complete` closes
them and the 32-bit read result: HRDATA20 reuses owned GND RMUX03 through the
alternate exact ingress BBMUXE07 and HRDATA27 reuses owned GND RMUX90 through
BBMUXW02. Exact 32-bit scratch reads had zero errors across 256 word values
and 128 mixed pairs; bitgen used 662 data PIPs, 624 recovered mappings, and
zero legacy, predicted, or unmapped selectors.

Record `2026-08-05-l48-wait8-haddr0-simultaneous-sticky` qualifies
simultaneous HADDR0 logic ingress on that composition. One scratch6 readback
branch moves to a three-hop strict alternative, freeing InputMUX11-to-RMUX87
for HADDR0; a resettable sticky at X14Y10 slice0 observes it. An even byte
read at offset +4 returned `0x5a` with word witness `0x0000005a`; an odd byte
read at +5 returned zero and set the sticky word witness `0x8000005a`; GPIO
reset restored zero. Routing HADDR0 alone is not byte support: the ungated
follow-on failed every subword class and is retained as
`2026-08-05-l48-wait8-access-pre-gating-negative` (the accepted-write commits
must consume the low-address decode; do not rerun the ungated composition).
Record `2026-08-05-l48-wait8-aligned-byte-halfword-complete-bank` then closes
aligned subword semantics for the complete one-byte bank: HADDR1 uses its
exact BufMUX11/InputMUX10/RMUX74 root, a combinational `HADDR[1:0]==0` decode
gates both scratch and status commits, and upper response bytes are the
already-qualified explicit zeros. Silicon passed 256 low-byte writes, 256
three-upper-byte preservation groups, byte reads, 256 low-half writes, 256
upper-half preservation cases, halfword reads, and the ID/counter/W1C class
oracle. The register-window soft UART
(`2026-08-05-soft-uart-register-window-offline`) is an offline artifact gate
only; see [MCU_AHB_SOFT_UART.md](MCU_AHB_SOFT_UART.md).

Record `2026-08-11-l48-misaligned-access-fault-boundary` closes the
misaligned-access question at the MCU boundary. On the wait8 access-semantics
image, all twenty misaligned cases trapped synchronously with zero completions
and zero state mutation: fabric-window loads raised mcause 5 and stores
mcause 7 (load/store access faults — the transfers never reach the fabric
slave), while SRAM controls raised the ordinary mcause 4/6 address-misaligned
faults. Every load destination retained its canary, fabric scratch survived
all five misaligned stores, and the identical trap map reproduced across two
firmware builds. The protocol core's misaligned-HRESP path is therefore
CPU-unreachable on the attached MCU; aligned byte, halfword, and word
transfers are the complete reachable transfer surface. This characterizes the
hard core's fault boundary and does not alter the retired
HRESP-to-architectural-fault result for protocol-valid aligned transfers.

Records `2026-08-05-l48-wait7-aligned-halfword-word-low-byte` and
`2026-08-05-l48-wait7-upper-hrdata-undriven-negative` split the transfer-size
boundary. Real aligned `SH/LHU` and `SW/LW` loops each covered all 256 low-byte
values with zero mismatch, and 128 mixed halfword/word pairs also passed the
`value & 0xbf` projection. Halfword and word store loops added 2533 and 2836
cycles over matched SRAM. However, the image instantiates only HRDATA[7:0]:
halfword reads were `0xffxx`, word reads were `0xffffffxx`, and all 768 upper-
lane checks were nonzero. Exact halfword/word reads therefore remain
fail-closed pending explicit upper-zero response lanes. This is not byte or
burst qualification.

The next bounded composition relocates only the HRDATA7 exit from RMUX79 to
the strict RMUX56 ingress, then fans the existing explicit GND LUT at X15Y12
slice8 onto HRDATA8. Strict bitgen maps 545 of 560 data PIPs with zero guessed
or unmapped selectors, and offline simulation binds `mcu_h0` through `mcu_h8`
to the exact AHB lanes. On L48 silicon, 256 aligned halfword cases, 256 aligned
word cases, and 128 mixed pairs had zero low-byte and zero bit-8 errors. The
halfword OR/AND became `0xfebf`/`0xfe00`, the word OR/AND became
`0xfffffebf`/`0xfffffe00`, waits remained live, and reset returned
`0xfffffe00`. This qualifies HRDATA8 zero and preservation of the relocated
HRDATA7 path only. All 768 residual observations above bit8 remained nonzero;
HRDATA[31:9], exact wider reads, byte transfers, and bursts remain open.

HRDATA9 then uses the free exact RMUX13 ingress. Its GND branch starts at the
already-owned X15Y11 RMUX08 wire and adds no readback relocation. Strict
bitgen maps 552 of 568 data PIPs with zero guessed or unmapped selectors; all
615 routed PIPs are present in the strict graph without a cross-net wire
conflict, and offline binding is exact through `mcu_h9`. Silicon again passes
all 256 halfword, 256 word, and 128 mixed cases with zero low-byte or
bits8–9 errors. Halfword OR/AND is `0xfcbf`/`0xfc00`, word OR/AND is
`0xfffffcbf`/`0xfffffc00`, waits remain live, and reset returns
`0xfffffc00`. This qualifies HRDATA9 zero; HRDATA[31:10] and exact wider reads
remain open.

HRDATA10 uses free exact ingress RMUX72, one strict hop from the already-owned
GND RMUX19 wire, with no readback relocation. Strict bitgen maps 554 of 571
data PIPs with zero guessed or unmapped selectors; all 618 route PIPs are in
the strict graph without a cross-net conflict, and offline binding is exact
through `mcu_h10`. Silicon passes every low-byte and bits8–10 check. Halfword
OR/AND is `0xf8bf`/`0xf800`, word OR/AND is
`0xfffff8bf`/`0xfffff800`, waits remain live, and reset returns
`0xfffff800`. HRDATA[31:11] and exact wider reads remain open.

HRDATA11 uses the nearer free RMUX48 ingress, branching from the already-owned
X20Y12 RMUX56 GND corridor without moving a readback route. Strict bitgen maps
559 of 577 data PIPs with zero guessed or unmapped selectors; all 624 route
PIPs are strict and conflict-free, and offline binding is exact through
`mcu_h11`. Silicon passes every low-byte and bits8–11 check. Halfword OR/AND
is `0xf0bf`/`0xf000`, word OR/AND is `0xfffff0bf`/`0xfffff000`, waits and
reset remain live. HRDATA[31:12] and exact wider reads remain open.

Neither free HRDATA12 ingress was reachable from the existing GND tree without
crossing a live route. The qualified registered-zero scratch6 net already owns
X14Y10 RMUX25, which reaches free exact RMUX00 in one hop. Fanning that net to
HRDATA12 moves no readback route. Strict bitgen maps 561 of 580 data PIPs with
zero guessed or unmapped selectors; all 627 route PIPs are strict and
conflict-free; offline binding is exact through `mcu_h12`. Silicon passes
every low-byte and bits8–12 check. Halfword OR/AND is `0xe0bf`/`0xe000`, word
OR/AND is `0xffffe0bf`/`0xffffe000`, waits and reset remain live.
HRDATA[31:13] remains open.

HRDATA13 has two free exact ingress candidates; the shorter strict GND branch
uses the already-owned X16Y11 RMUX20 source through RMUX75 and RMUX20. No
readback route moved. Strict bitgen maps 564 of 584 data PIPs with zero guessed
or unmapped selectors; all 631 route PIPs are strict and conflict-free;
offline binding is exact through `mcu_h13`. Silicon passes every low-byte and
bits8–13 check. Halfword OR/AND is `0xc0bf`/`0xc000`, word OR/AND is
`0xffffc0bf`/`0xffffc000`, waits and reset remain live. HRDATA[31:14] remains
open.

HRDATA14 also has two free exact ingress candidates. The shorter strict GND
branch starts at the already-owned X19Y9 RMUX15 wire and reaches RMUX26 in
four hops; no readback route moved. Strict bitgen maps 569 of 590 data PIPs
with zero guessed or unmapped selectors; all 637 route PIPs are strict and
conflict-free; offline binding is exact through `mcu_h14`. Silicon passes
every low-byte and bits8–14 check. Halfword OR/AND is `0x80bf`/`0x8000`, word
OR/AND is `0xffff80bf`/`0xffff8000`, waits and reset remain live.
HRDATA[31:15] remains open.

HRDATA15's two exact ingresses were free but unreachable from either qualified
zero source without one live-route crossing. The minimum cut was the
`write_data_pipe5` X14Y10 RMUX69 wire. An equal-length strict route moves that
net from the same OMUX17 source to the same IMUX41 sink through five free
intermediate wires, after which the qualified registered-zero scratch6 net
reaches HRDATA15 in four strict hops. All 643 route PIPs are strict and
conflict-free; bitgen maps 574 of 596 data PIPs with zero guessed/unmapped;
offline binding is exact through `mcu_h15`. Silicon returns exact zero-extended
aligned halfword values (`value & 0xbf`) in all 256 cases and 128 mixed pairs.
Halfword OR/AND is `0x00bf`/`0x0000`; word OR/AND is
`0xffff00bf`/`0xffff0000`; waits and reset remain live. HRDATA[31:16] and exact
word reads remain open.

The coherent HWRITE/HWDATA[1]/HBURST2 footprint remains represented. Later
diagnostics recovered the actual retained group-1 owners rather than extending
the earlier dead candidate: HWDATA[6] reaches X14Y12 slice15 `I[0]`, and a
fresh registered capture matched 64/64 patterns; HWDATA[7] reaches X14Y11
slice0 `I[1]`, as reinterpreted from the 64/64 qualified group image. The
paired HWRITE/HTRANS1 write qualifier reaches X14Y12 slice0 `I[0:1]` in every
qualified write group. These are exact consumer footprints, not freely
permutable MCU-input pins.

The first proposed fanout architecture remains dead: reusing HWDATA[6]'s
X14Y12 slice15 site as a combinational identity root returned constant
`0xffffffdf` for 64/64 writes (record
`2026-08-04-hwdata6-x14y12-slice15-identity-t01`). The successful replacement
is a complete posted footprint, not a transparent fanout assumption. Record
`2026-08-04-l48-hwdata0-busclock-capture-exact-site` qualifies HWDATA0 under
MCU_BUS_CLOCK at X14Y11 slice5. Record
`2026-08-04-l48-scratch1-posted-forwarding-complete-footprint` combines that
capture with DD88 registered storage at slice7 and FC0C same-register
forwarding at slice14. Its SRAM sequence was exactly `010101010101`, including
two back-to-back-write cases where the newest value won. Scope is one aligned
one-bit register with posted completion; it does not imply a decoded address
tag, reset, waits, errors, byte access, wider storage, or unrestricted sites.
The bank now widens this architecture one qualified HWDATA lane at a time.
Sparse pin permutation remains inadmissible.

That first address-tag extension is now silicon-qualified by record
`2026-08-04-l48-scratch1-posted-address-tag`. HADDR[2] has one registered
consumer; offset 0 retains the one-bit writable store, while offset 4 reads
zero and ignores writes. The observed sequence `00100001` covers immediate
same-address forwarding, no cross-address leakage, persistence, ignored
offset-4 writes, and back-to-back newest-write behavior. This still is not a
second writable register or a wider data claim for that retained image.

Record `2026-08-04-l48-hwdata1-busclock-capture-exact-site` adds the exact
HWDATA1 X14Y10 slice3/I1 consumer and retained OMUX11-to-HRDATA1 exit. Record
`2026-08-04-l48-scratch2-posted-address-tag` then qualifies a two-bit scratch
at offset 0: all values 0 through 3, immediate forwarding, both back-to-back
write orders, persistence, no cross-address forwarding into offset 4, and an
ignored offset-4 write. The observed sequence was `0012321033`.

Record `2026-08-04-l48-scratch3-posted-address-tag-pure-open` extends that
atom to HWDATA2 without an experimental option. The exact sequence
`001234567630777` covers all values 0 through 7, both back-to-back write
orders, persistence, offset-4 isolation, and ignored offset-4 writes. Lane2
state is consumed on the same X14Y11 tile; live HADDR2 performs read selection
while the registered address tag remains the write-phase tag. Two registered-
address routes that read constant high remain retained negatives. Record
`2026-08-04-l48-hwdata3-busclock-capture-exact-site` separately qualifies
HWDATA3 at X15Y12 slice0/I1 with the exact sequence `010101010101`.

Record `2026-08-04-l48-scratch4-posted-address-tag-pure-open` extends the
same atom to four stored bits. The exact sequence
`0 0 1 2 3 4 5 6 7 8 9 a b c d e f c 3 0 f f f` covers every value 0 through
15, both back-to-back orders, persistence, HADDR2-tagged offset-4 isolation,
and ignored offset-4 writes. The lane-three storage cell remains at X15Y12
slice0 with its qualified HWDATA3 I1 consumer; a separate X14Y11 slice3 read
gate supplies HRDATA3. The immediately preceding ungated discriminator
returned `0x8` only on the offset-4 read while all storage checks passed, so
the retained negative identifies the missing read gate rather than a storage
or ingress failure. Later records in this ledger qualify writable lanes 4
through 7 and the integrated GPIO reset; writable-bank waits and byte/halfword
behavior remain open, while the MCU access-fault interpretation of HRESP is
retired as described above.

HWDATA4 is now independently exact at the free X15Y12 slice2 site. All four
input terminals I0 through I3 returned `010101010101` under MCU_BUS_CLOCK;
the bank reserves I1 so I0 remains available for the posted commit and I3 for
direct-D feedback. The four X14Y12 slice2 terminal candidates were uniformly
constant one and remain retained negatives. This qualifies the HWDATA4
consumer family and its four exact routes.

Record `2026-08-04-l48-scratch5-posted-address-tag-pure-open` closes five-bit
storage at that site. All values 0 through 31, both back-to-back orders,
persistence, offset-four isolation, and ignored offset-four writes passed.
The image hash is
`1a23a66ed1ec75b2adeb8b6b6665e4c307c7a948a3abb7b0abf26f5792ec001e`.
HWDATA5 is live on all four X14Y11 slice5 terminals. HWDATA0 is also live
directly at the existing lane-zero storage I1 terminal. Direct-control six-bit
variants preserved the complete lower-five behavior but returned lane5
constant one across commit I0/I1/I2, a local qualifier, and two buffer
assignments. These are retained coupled negatives, not dead-PIP claims.
Record `2026-08-04-l48-scratch6-next-state-mux-pure-open` closes the boundary:
slice5 captures HWDATA5 on its exact live path, a separate combinational LUT
applies commit/hold, and an ordinary slice8 DFF stores the single next-state
input. Two exact characterized route-throughs distribute the commit root and
are constructively pre-routed onto their required final edges. The observed
74-value sequence includes reset zero, every value 0 through 63, both
back-to-back orders, persistence, offset-four isolation, and ignored offset-
four writes.

Record `2026-08-04-l48-scratch7-folded-slice15-pure-open` extends the
qualified footprint through lane6. The exact HWDATA6 path still terminates at
X14Y12 slice15/I0. Because its qualified Q corridor is MCU-only, commit/hold is
folded into the same BB88 storage equation: I0 is HWDATA6, I1 is the high
commit leaf, and I3 is own Q. The constant-high HREADYOUT source moves to
X15Y12 slice12 on a strict-clean route. The 135-value observation sequence
contains reset zero, every value 0 through 127, both back-to-back orders,
persistence, offset-four isolation, and an ignored offset-four write. Image
SHA-256 is
`82cbb7301af1b82252f08c1214a3ee12012f46b7a1e173380bcf021fbb1dc2be`.
Integrated reset, the remaining register classes, writable-bank waits, and
byte/halfword behavior remain separate claims; HRESP-to-fault behavior is
retired.

Record `2026-08-04-l48-scratch8-folded-slice0-pure-open` closes the writable
byte. HWDATA7 remains on its exact X14Y11 slice0/I1 terminal; the qualified
low commit leaf reaches I2 and own-Q hold reaches I0, so `CACA` implements
the complete storage equation without a guessed selector. The lane1
forwarding mux moves to free X14Y11 slice15. The exact 263-value observation
contains reset zero, every value 0 through 255, both back-to-back orders,
persistence, offset-four isolation, and an ignored offset-four write. Image
SHA-256 is
`c6f9bf61873ba74a3f50e79c956754c0230f7349913e8e48a3d688aeabd636db`.
Record `2026-08-04-l48-id-scratch8-pure-open` qualifies the first two
register classes. Offset zero returns immutable ID low byte `0x4d`; offset
four is reset-zero writable scratch and passes all 256 byte values, both
back-to-back orders, ignored ID writes, and scratch preservation. Image
SHA-256 is
`4cd1551d1202c9768554b75deddcace93291e8444b6d6c82f9762936a7dc737b`.
The standalone counter record
`2026-08-04-l48-counter3-register-pure-open` qualifies a lower-three-bit
read-only register at offset eight. Its qualified 48-sample suffix covers all
eight states at constant modulo-eight delta seven; a write of `0xff` has no
effect, counting continues, and offsets zero/four/C return zero. It uses the
exact slice4/6/7 direct-D counter, a registered address-phase select, and
causally qualified read branches. Record
`2026-08-04-l48-w1c-status1-pure-open` separately qualifies one-bit status at
offset C. A qualification-only software-set hook on write bit1 supplies an
internal event without a package pin; write bit0 clears. The exact silicon
sequence covers reset zero, set, eight holds, zero-write no-op, W1C clear,
wrong-offset set isolation, re-arm, a second clear, and simultaneous set/clear
with set priority. Record
`2026-08-05-l48-combined-register-bank-pure-open` then qualifies all four
classes in one selector-clean image. ID remains `0x4d`; scratch returns every
byte value and survives status traffic; ID and counter writes are ignored; a
fixed counter window advances at constant nonzero modulo-eight delta two and
an independent bounded phase sweep covers all eight states; and the complete
W1C sequence passes with set priority. The integrated counter uses the already
qualified seeded X15Y1 dedicated-carry footprint. W1C events reuse
fabric-local outputs of the qualified low-lane forwarding paths rather than
adding a hard HWDATA selector. Integrated reset, writable-bank waits, and
byte/halfword transfer semantics remain separate claims; HRESP-to-fault
behavior is retired.

That widening also exposed why complete footprints are policy rather than
documentation. An automatically placed identity LUT at X14Y8 slice8 used
`RMUX76 -> IMUX32` instead of its characterized `RMUX00 -> IMUX32` footprint
and returned lane1 as constant one (`2232323233`). Bypassing only that buffer
made the two-bit oracle pass. Strict bitgen therefore rejects that exact
site/INIT with a non-footprint final edge; other sites are not generalized
beyond their own silicon evidence.

Record `2026-08-05-l48-combined-bank-gpio-reset-pure-open` composes the
qualified GPIO4.1 ingress with the combined bank. While reset is asserted,
scratch, status, and counter remain zero, scratch/status writes are blocked,
and immutable ID remains `0x4d`. Two releases re-arm all state classes and two
reassertions clear them again. This is synchronous GPIO-fed reset, not hard
`MCU_RESETN`, POR, option-byte, or equal post-release phase qualification.
Aligned word read/write and back-to-back behavior are already covered by the
combined-bank sequence; halfword access remains separate, while HRESP-to-fault
behavior is retired. Record `2026-08-05-l48-controlled-wait-id-pure-open` separately
qualifies the response controller on an immutable-ID endpoint. Under released
reset, 256 reads were all `0x4d` and added 3849 MCU cycles over matched SRAM
loads; 256 ignored writes added 2279 cycles over matched SRAM stores and left
ID unchanged. Reset assertion forces ready and preserves ID. This scope is one
single aligned word transfer at a time, not bursts, byte/halfword access, or a
writable-bank wait claim. Two preceding writable-bank images retain the wait
timing but corrupt lane6; the separate-capture retry confirms the already
recorded MCU-only capture-Q boundary and must not be rerun. The retained
evidence is
`qualification/mcu_ahb_constant_slave_evidence.jsonl`,
`qualification/mcu_bus_clock_evidence.jsonl`, and
`qualification/mcu_haddr5_logic_evidence.jsonl` plus
`qualification/mcu_haddr3_logic_evidence.jsonl`,
`qualification/mcu_haddr4_logic_evidence.jsonl`,
`qualification/mcu_hwdata_logic_route_evidence.jsonl`, and
`qualification/mcu_ahb_register_bank_evidence.jsonl`.

Record `2026-08-05-l48-register-bank-nonsingle-bursts-retired` closes the
burst boundary without broadening the silicon claim. In the qualified waited
bank, the recovered exact HBURST0 and HBURST1 logic exits require RMUX56 and
RMUX49, which are already owned by readback[7:6]; HBURST2's recovered RMUX63
exit is owned by readback[5]. The attached firmware path has no autonomous
non-SINGLE External-AHB source under the SRAM-only/no-wiring rails. The public
protocol core therefore latches HBURST and accepts only `3'b000`; simulation
checks all seven other encodings on reads and writes, asserting HRESP, returning
zero on invalid reads, preserving scratch, and retaining later SINGLE
readback. This is fail-closed protocol behavior, not a claim that HRESP raises
an MCU exception.

Record `2026-08-05-l48-ahb-local-int1-command-bank-pure-open` composes the
qualified offset-four scratch write, offset-C W1C state, GPIO4.1 reset, and
the exact cause-17 corridor. Offset four bit0 writes mask/unmask; offset C
bit1 is a qualification-only pending-set hook and bit0 acknowledges. The
SRAM-only sequence retained an event while masked, delivered three exact
cause-17 traps with two independent re-arms, held the third event at trap
count two while masked, delivered it once after unmask, cleared `mip[17]`
after each acknowledge, and cleared the line on reset. Reads return zero and
no state-read claim is made. Unused local causes must remain disabled; their
default `mip` bits can read high. The attached MCU did not expose local
`mip[17]` until `mie[17]` was armed, so pre-enable visibility is outside the
claim. At that record boundary, four-lane routing/cause delivery was qualified
independently while command-state widening remained open.

Record `2026-08-05-l48-ahb-local-int2-command-bank-pure-open` reuses the same
command-state implementation and fail-closed read boundary at the independent
X10Y4 cause-18 source. Trap counts advanced exactly `1/2/3`, all three causes
were `0x80000012`, every acknowledge cleared `mip[18]`, masked hold and
unmask delivery passed, and GPIO4.1 reset cleared the line. Strict bitgen used
191 data PIPs with 179 recovered mappings and no guessed or unmapped selector.
At that stage, causes 16 and 19 remained open for command-state composition.

Record `2026-08-05-l48-ahb-local-int3-command-bank-pure-open` moves only the
final gate and sink to the independent X14Y4 cause-19 source. Trap counts
advanced exactly `1/2/3`, all causes were `0x80000013`, acknowledgements
cleared `mip[19]`, masked hold/unmask delivery passed, and GPIO4.1 reset
cleared the line. Strict bitgen used 190 data PIPs with 178 recovered mappings
and no guessed or unmapped selector. At that stage, cause 16 was the sole open
command-state lane.

Record `2026-08-05-l48-ahb-local-int0-command-bank-pure-open` closes the final
lane without displacing the X14Y12 slice0 source. HADDR2 selects one explicit
composite write class and HADDR3 is not consumed, so offsets four and C are
supported aliases. Commands `00/01/10/11` mean mask-off/hold, mask-on/ack,
mask-off/set, and mask-on/set. Pending and mask both use the qualified delayed
commit and forwarded-data phase. Trap counts advanced exactly `1/2/3`, all
causes were `0x80000010`, acknowledgements cleared `mip[16]`, masked hold and
unmask delivery passed, and GPIO4.1 reset cleared the line. Strict bitgen used
182 data PIPs with 170 recovered mappings and no guessed or unmapped selector.
All four per-lane command-state subsets were therefore qualified.

Records `2026-08-05-l48-ahb-local-int-all-command-bank-lane0-pure-open`
through `lane3` close the one-image integration gate with an explicit narrower
state model. HWDATA[3:2] selects one of the four exact output gates and
HWDATA[1:0] applies the same composite commands at offset 4. The image retains
one shared pending/mask pair and exposes it through exactly one selected cause;
it does not claim four simultaneous pending stores. One SRAM-only MCU run
counted `3/3/3/3`, observed causes `0x80000010` through `0x80000013` with the
matching one-hot trap-time `mip` bit, acknowledged every delivery, re-armed
twice per cause, held the first and third events behind the mask, and cleared
all local bits on GPIO4.1 reset. Reads return zero. Strict bitgen used 251 data
PIPs with 236 recovered mappings, no predicted, legacy, or unmapped selector,
and closed the 10 MHz constraint at 87.23 MHz. State readback, pre-`mie`
visibility, and simultaneous per-lane pending storage remain outside the claim.

Record `2026-08-05-l48-ahb-local-int-preconfig-reset-clock` characterizes the
remaining reset/clock boundary without changing the image. After the runner's
ordinary board reset and before the SRAM image was sent to the FCB, local
`mip[19:16]` was zero both with local `mie` clear and with all four bits armed
while global interrupts stayed disabled. Holding GPIO4.1 reset across
configuration produced zero local `mip` before and after release. With only
cause 16 armed, 64 set and 64 acknowledge transitions each completed in
exactly 21 MTIME ticks, and synchronous GPIO reset cleared an asserted line in
40 ticks. The image clocks every transaction and state stage from
`MCU_BUS_CLOCK`; the timing statement composes with the separate 1:1 proof for
default `bus_clk = sys_gck` against undivided MTIME. The pre-load sample
is an attached-board post-reset observation, not POR, blank-fabric, flash,
option-byte, persistent-state, PLL3 BUSCLK, alternate-clock, hard
`MCU_RESETN`, asynchronous-reset, or equal post-release-phase qualification.

## Exact 16-bit held-scratch checkpoint

Record `mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815`
qualifies a separate width checkpoint. Sixteen state LUT/FFs use external
identity-LUT feedback, avoiding own-Q direct-D entirely, while the qualified
HREADYOUT controller inserts one write wait so HWDATA is sampled in its data
phase. Fifteen state cells retain the posted-capture placements; lane 12 moves
because the wait controller owns its former site.

The SRAM-only oracle exercised 100 aligned word values. Immediate reads,
reads after SRAM churn and elapsed time, and repeated reads all returned the
written low 16 bits; GPIO4.1 reset returned all lanes to zero. The strict image
has 407 pips / 388 mapped, zero predicted, legacy or unmapped selectors, and
meets 79.71 MHz against 10 MHz. Its retained routed JSON repacks to the exact
silicon image.

This checkpoint does **not** replace the complete-byte public bank. Its only
qualified storage object is one 16-bit scratch word. The original churn
firmware did not write another External-AHB address, so that trial made no
address-isolation claim.

A deterministic derivative, recorded as
`mcu-ahb-register-bank16-haddr32-write-isolation-silicon-20260815`, preserves
the sixteen state cells, feedback paths, wait controller, HWDATA inputs and
HRDATA[15:0] exits. It adds exact HADDR2/HADDR3 inputs and gates the qualified
HWRITE path at X14Y12 slice0. Across 100 patterns, writes to +4, +8 and +c did
not change +0, and a following valid +0 write still overwrote the state. Reads
at +4/+8/+c intentionally returned the same +0 value. The claim is therefore
**write-commit isolation through HADDR[3:2]**, not full or read-side address
decoding. Upper HRDATA zeros, bursts, arbitrary widths or placement, and
integration with ID/counter/W1C remain open.

The adjacent HSIZE[1] prerequisite is independently closed on one exact route:
256 word/halfword/byte trials at a fixed address observed the expected 1/0/0
identity result after replacing the incorrect generic selector with the
vendor-measured RMUX34 codeword.

Record `mcu-ahb-register-bank16-word-byte-waited-silicon-20260815` composes
that control with the held state. Independent pending tokens capture the low
and high bytes; the high token is ready-qualified and uses an all-physical
replacement route for `hwrite_word0`. Four complete 100-pattern runs passed:
word writes changed both lanes, byte +0/+1 changed only the addressed lane,
byte +2/+3 and aligned writes +4/+8/+c preserved word zero, overwrites worked,
and GPIO reset cleared/re-armed the state. The strict image has 467 data pips
and zero legacy-absolute, predicted or unmapped selectors.

Record `mcu-ahb-register-bank16-word-byte-halfword-waited-silicon-20260815`
adds HSIZE0 through its vendor-exact
`BufMUX03â†’InputMUX03â†’RMUX41â†’IMUX15` ingress. The two existing selector
LUTs now compute `!HADDR1 && (HADDR0 || HSIZE1 || HSIZE0)`, qualified by
HTRANS1; the downstream HWRITE/write-ready/reset handshake and all sixteen
capture cells are retained. HREADY-safe identity/zero controls produced masks
`0x002` and `0x000` respectively across 64 patterns in each of nine transfer
classes. Four full 100-pattern runs then passed aligned word +0, aligned
halfword +0, independent byte +0/+1, rejection of byte +2/+3, aligned
halfword +2/+4/+8/+c and aligned word +4/+8/+c, overwrite, and GPIO reset.
The strict image has 471 data pips and zero legacy-absolute, predicted or
unmapped selectors; its hash-gated composer reproduces the tested image
byte-identically.

Record `mcu-ahb-register-bank16-read-word0-isolation-silicon-20260815` adds a
read-only `!HADDR2 && !HADDR3` decoder and sixteen output gates while preserving
all capture-to-feedback paths exactly. Ten sequential SRAM-only runs covered an
ungated pre/post baseline, constant-one, constant-zero, separate `!HADDR2` and
`!HADDR3` controls, and four real-decoder repeats. Low-16 aligned word reads at
+0/+4/+8/+c returned `[state, 0, 0, 0]`; the complete word/halfword/byte write,
retention, overwrite, one-wait, and reset matrix stayed green.

Record `mcu-ahb-register-bank16-cpu-subword-read-silicon-20260815` exercises
that same image with compiler-audited real `LBU` and aligned `LHU` instructions.
An independent SRAM canary first proves the hard core's little-endian lane
selection and zero extension. Three fabric runs then pass 32 retained patterns
and 128 observation groups each: `LBU +0/+1` select the retained low/high bytes,
`LHU +0` returns the retained word, `LBU +2/+3` and `LHU +2` select the
corresponding bytes/halfword from the same raw word, every unsigned result
zero-extends, and reads do not mutate state. The observed raw upper half was
`0xffff`; it is diagnostic, not a characterization of HRDATA[31:16].

The final checkpoint topology is also reproducible from a generated structural
Verilog fixture. `--qualified-checkpoint mcu-ahb-bank16-read-word0` compares the
post-Qin source and checkpoint by all 101 primitive types/parameters and all 83
complete producer/consumer net signatures, then replays exact BEL and per-net
route ownership without invoking nextpnr. This is a closed registry, not a path
to arbitrary JSON: source/checkpoint hashes, HSE=8, SYSCLK=10, default packaged
data, build options and the final raw/compressed hashes are mandatory. The
outputs reproduce SHA-256 `301edbab...5160` and `5b90b852...f9bae`
byte-for-byte with zero route debt. This closes source-to-qualified-route
reproducibility for the exact fixture; it does not turn checkpoint-derived
structural RTL into a generic register-bank generator.

A second registered profile, `mcu-ahb-bank16-public-scratch4`, changes exactly
two LUT truth tables: `hwrite_word0_gate` moves `0x0044 -> 0x0088`, and
`read_word0` moves `0x1111 -> 0x2222`. All 101 BELs and 83 routes remain
identical; strict packing changes only the six derived LUT config bytes and CRC.
Three complete SRAM-only runs pass 32 retained patterns and 160 observations
each: aligned word and halfword writes at +4, independent bytes +4/+5,
width-appropriate rejection at +0/+6/+8/+c, low-16 word reads
`[0,state,0,0]`, aligned unsigned subword selection/zero extension, retention,
GPIO reset clear, and valid-write blocking while reset is asserted. A retained
+0 post-campaign control passed, while the +4 oracle rejected the +0 image with
the expected address-dependent errors. This qualifies one exact scratch object
at the public scratch offset. The composition below supersedes its
coexistence limitation without widening its exact-width storage claim.

## Exact composed public16 map

Record `mcu-ahb-public16-exact-map-silicon-20260815` composes the qualified +4
scratch spine with immutable ID8 `0x4d` at +0, a free-running three-bit counter
at +8, and one-bit W1C status at +c. The status experiment uses a
qualification-only set hook (write bit 1), clears on write bit 0, and gives set
priority. It is not a claim for a production event source.

Four sequential volatile-SRAM runs of the final deterministic image passed
with FCB `0x000f0002`, all eight error groups zero, all eight counter states
seen, and final low-16 words `[0x004d,0,0,0]` after reset. The oracle covers
aligned word/halfword and independent byte +4/+5 scratch writes,
representative foreign-address isolation, decoded word/subword reads,
retention, coexistence, counter range/liveness, W1C set/clear/set-priority, and
GPIO4.1 reset. No flash command was issued.

The composer starts from the exact 101-cell +4 checkpoint, permits LUT/input
changes only in six named overlay cells, preserves ten extended base routes as
exact prefixes, and adds eighteen exact cells. An independent checker rejects
unreviewed cell changes, route removal, duplicate BELs, cross-net wire reuse,
or a structural-source mismatch. The resulting 119-cell/103-routed-net image
packs with 720 data pips, 698 mapped, and zero legacy-absolute, predicted, or
unmapped selectors. The routed, raw, and compressed SHA-256 values are pinned
as `aa7ff307...c5fe`, `3fd36e5b...f481`, and `beda2dbe...25fb`.

The SDK profile `l48-public16-exact-map-2026-08-15` remains available as a
preserved narrower checkpoint. Its source is a generated exact
route-replay fixture, not portable canonical RTL or a generic register-bank
generator. The prior `l48-complete-byte-waited-2026-08-05` profile remains
available.

Misaligned and signed loads, raw HRDATA[31:16] behavior, canonical 32-bit ID
`0x4147414d`, higher/full slave-window decode, bursts on the new composition,
a generic application-owned status-set socket, arbitrary placement/width, and other devices or
packages remain open. This is an exact aligned-transfer L48 composition, not a
generic 16- or 32-bit bank.

## Exact composed public32 map

Record `mcu-ahb-public32-exact-map-silicon-20260815` widens the preserved
public16 checkpoint to every raw HRDATA lane. Offset +0 now returns canonical
ID `0x4147414d`; scratch16, counter3, and W1C1 at +4/+8/+c return exact
zero-extended 32-bit words. Three sequential volatile-SRAM runs passed with
FCB `0x000f0002`, all nine error groups zero, counter coverage `0xff`, eight
scratch patterns, and reset-final words `[0x4147414d,0,0,0]`.

The full oracle uses unmasked `LW`, checks all four ID bytes and both ID
halfwords plus CPU unsigned-load zero extension, and repeats the entire
scratch word/halfword/independent-byte, foreign-write, counter, W1C
set/clear/set-priority, reset-held-write and GPIO-reset matrix. No flash command
was issued.

The deterministic composer retains all 119 public16 cells, changes only the
INIT/input selection of `read_gate8` and `read_gate14`, adds sixteen exact
MCU_DOUT exits plus one ID-selector LUT, and relocates one
`public_status_pending` branch while preserving the wait, set, and clear
consumers. The 136-cell/104-routed-net image packs with 809 data pips and zero
legacy-absolute, predicted, or unmapped selectors. The checker also requires
the encodable HRDATA28 RMUX90 tail and rejects the superficially routable but
unencoded RMUX42 alternative. Routed/raw/compressed SHA-256 values are pinned
as `ab76df40...c574`, `ac33ca6b...e6f5`, and `ee5c4643...6cba`.

`l48-public32-exact-map-2026-08-15` is now the `mcu-fpga-registers` template
default. The source remains a mechanical route-replay fixture, not portable
canonical RTL or a generic register-bank generator. Scope is the four aligned
HADDR[3:2] classes on L48 at HSE=8/SYSCLK=10. A generic application-owned status-set socket,
misaligned/signed accesses, full-window decode, bursts, arbitrary
placement/width, and other devices/packages remain open.

## Exact GPIO5 level-set W1C derivative

Record `mcu-ahb-public32-gpio5-w1c-level-silicon-20260815` qualifies a
separately selectable derivative of that exact public32 checkpoint. It removes
only the qualification HWDATA1/status-pending branches into
`public_set_event`, adds `MCU_GPIO5_OUT_DATA0` at the qualified lane-0 hard
boundary, relays it through `X9Y4_SLICE3.I3`, and retains the existing
HCLK-registered set stage, clear stage, storage, wait logic, and public map.

One common full-map firmware makes the causality explicit. The unchanged base
image returns `status_errors=162`: GPIO5 cannot set it and bit1 still can. An
OR-control containing both sources returns `2`: all GPIO phases work, and only
the intentionally retained bit1 hook violates production semantics. Three
production runs return all nine error groups zero, `seen=0xff`, eight scratch
observations, and reset-final `[0x4147414d,0,0,0]`. Every run is volatile SRAM,
FCB `0x000f0002`, with cleanup reset and no flash operation.

The measured contract is level-sensitive: GPIO5 DATA0 low permits hold and
W1C bit0 clear; sustained high sets or reasserts with set priority; deasserting
retains the stored bit; reset dominates high, and releasing reset while high
sets again. The former AHB bit1 set hook is inert. The 138-cell/106-routed-net
image packs 814 pips with zero legacy, predicted, or unmapped selectors.

This is not a generic `STATUS_SET` owner. GPIO5 DATA0/OUT_EN0 is
software-controlled qualification stimulus, not a package-pin input,
autonomous peripheral event, asynchronous interrupt, edge detector, pulse/CDC
guarantee, or debounce circuit. A generic application-owned status socket remains
open, as do the other public32 exclusions above.

## Exact autonomous synchronous W1C derivative

Record `mcu-ahb-public32-autoevent-w1c-silicon-20260816` qualifies a second
selectable derivative. The existing three-bit HCLK-synchronous fabric counter
feeds a count-seven detector and reset-rearmed one-shot. The event sets status
without an AHB set write or GPIO stimulus, disarms while status retains, clears
through W1C bit0, and repeats once after reset. An unchanged negative returned
signature `0x04`, the dual-source OR control `0x15`, and three production runs
`0x11`, with the rest of the public32 matrix zero-error in every run.

This is one pinned synchronous source. It is not a generic user-net
`STATUS_SET` socket, asynchronous pulse/CDC contract, interrupt controller,
event ABI, arbitrary application overlay, or generic bank.
