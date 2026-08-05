# MCU External AHB register bank

Status: the response-source allocation gap is closed. The release backend now
matches response drivers globally and negotiates the full `HRDATA[31:0]`,
`HREADYOUT`, and `HRESP` corridor set without router1 legality failures. The
combinational constant-ready/OKAY endpoint builds with strict bitgen and is
silicon-qualified on L48. Pure-open `MCU_BUS_CLOCK` delivery now runs an
explicit three-bit counter at the exact qualified X14Y11 slice4/6/7 direct-D
sites and exposes all eight states. A separate 16-bit LFSR produces 500
distinct states and advances exactly once per undivided 10 MHz MTIME tick.
An explicit GPIO4.1-fed synchronous reset also holds that LFSR at zero and
re-arms it. One strict combined register-bank image now qualifies immutable
ID, writable scratch, read-only counter, and W1C status behavior, and a second
strict image integrates that GPIO reset with every state class. A separate
immutable-ID endpoint qualifies exactly one controlled wait for every single
aligned word read or ignored write. A third strict image composes one
controlled write wait with scratch lanes 0–5 and 7 while lane 6 fails closed
to zero. Hard `MCU_RESETN`, a full-byte waited bank, bursts, and byte/halfword
semantics remain open. Deterministic MCU exceptions
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
- byte access is disabled because `HADDR[0]` does not yet have a qualified
  simultaneous LUT-input corridor; byte requests complete with `HRESP=1`;
- the wrapper observes address bits `[5:1]` for its near-window decode; unseen
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
default `bus_clk = sys_gck` against undivided 10 MHz MTIME. The pre-load sample
is an attached-board post-reset observation, not POR, blank-fabric, flash,
option-byte, persistent-state, PLL3 BUSCLK, alternate-clock, hard
`MCU_RESETN`, asynchronous-reset, or equal post-release-phase qualification.
