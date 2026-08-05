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
re-arms it. The complete register bank below is still hardware-unqualified:
its hard `MCU_RESETN` boundary and wider simultaneous input placement remain open.
Isolated HADDR[5] and HADDR[3] logic-ingress oracles each pass 256/256
addresses; retained HADDR[4]^HADDR[5] evidence now also qualifies HADDR[4].
The paired HWRITE/HTRANS1 X14Y12 slice0 qualifier footprint and working
HWDATA[0], HWDATA[1], HWDATA[6], and HWDATA[7] registered consumer paths are
represented. A bounded pure-open three-bit posted-storage image now routes and passes all
eight values, immediate write/read, back-to-back newest-write forwarding, and
HADDR2-tagged offset isolation. The full bank remains unqualified because
writable lanes 3 through 7, integrated reset delivery, and the remaining hard-input
footprints are open.

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
address routes that read constant high remain retained negatives.

That widening also exposed why complete footprints are policy rather than
documentation. An automatically placed identity LUT at X14Y8 slice8 used
`RMUX76 -> IMUX32` instead of its characterized `RMUX00 -> IMUX32` footprint
and returned lane1 as constant one (`2232323233`). Bypassing only that buffer
made the two-bit oracle pass. Strict bitgen therefore rejects that exact
site/INIT with a non-footprint final edge; other sites are not generalized
beyond their own silicon evidence.

The long-period LFSR proves
ordinary multi-register clocked state but does not solve the bank's boundary
placement or hard reset. The long-period reset oracle separately proves that
qualified GPIO ingress can provide deterministic synchronous reset-to-zero and
re-arm; it does not silently substitute for the bank's hard reset. If the bank builds,
its first SRAM-only sequence is reset state, aligned word read/write, and
back-to-back transfers. Halfword access, controlled waits, and error
responses remain separate later claims. The retained evidence is
`qualification/mcu_ahb_constant_slave_evidence.jsonl`,
`qualification/mcu_bus_clock_evidence.jsonl`, and
`qualification/mcu_haddr5_logic_evidence.jsonl` plus
`qualification/mcu_haddr3_logic_evidence.jsonl`,
`qualification/mcu_haddr4_logic_evidence.jsonl`,
`qualification/mcu_hwdata_logic_route_evidence.jsonl`, and
`qualification/mcu_ahb_register_bank_evidence.jsonl`.
