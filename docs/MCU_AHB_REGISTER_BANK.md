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
strict image integrates that GPIO reset with every state class. Hard
`MCU_RESETN`, waits/errors, and byte/halfword semantics remain open.
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
read-only registers complete with `HRESP=1`. `WAIT_STATES` inserts a bounded
number of response cycles. The corrected slave model decrements this internal
counter independently of `HREADY`; gating it with `HREADY` would deadlock
because the slave itself holds `HREADYOUT` low during the wait.

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
through 7 and the integrated GPIO reset; wait/error responses and
byte/halfword behavior remain open.

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
Integrated reset, the remaining register classes, wait/error responses, and
byte/halfword behavior remain separate claims.

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
adding a hard HWDATA selector. Integrated reset, wait/error responses, and
byte/halfword transfer semantics remain separate claims.

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
combined-bank sequence; halfword access, controlled waits, and error responses
remain separate claims. The retained evidence is
`qualification/mcu_ahb_constant_slave_evidence.jsonl`,
`qualification/mcu_bus_clock_evidence.jsonl`, and
`qualification/mcu_haddr5_logic_evidence.jsonl` plus
`qualification/mcu_haddr3_logic_evidence.jsonl`,
`qualification/mcu_haddr4_logic_evidence.jsonl`,
`qualification/mcu_hwdata_logic_route_evidence.jsonl`, and
`qualification/mcu_ahb_register_bank_evidence.jsonl`.
