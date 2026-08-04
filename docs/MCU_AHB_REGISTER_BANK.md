# MCU External AHB register bank

Status: the response-source allocation gap is closed. The release backend now
matches response drivers globally and negotiates the full `HRDATA[31:0]`,
`HREADYOUT`, and `HRESP` corridor set without router1 legality failures. The
combinational constant-ready/OKAY endpoint builds with strict bitgen and is
silicon-qualified on L48. Pure-open `MCU_BUS_CLOCK` delivery now runs an
explicit two-bit counter at the exact qualified X14Y11 slice6/7 direct-D
sites and exposes all four states. The sequential register bank below is
still hardware-unqualified: exact clock rate, deterministic reset, and
generic multi-register lowering remain open. Isolated HADDR[5] and HADDR[3]
logic-ingress oracles each pass 256/256 addresses. With both corridors
promoted, the unchanged bank advances to a simultaneous HWRITE/HWDATA[1]
placement conflict and still does not emit a routed image.

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

Next experiment: recover a simultaneously usable HWRITE/HWDATA[1]/HBURST2
placement corridor. A vendor-observed alternate HWDATA[1] terminal reaches
X14Y12 IMUX02 but does not, by itself, resolve the full-bank conflict; it is
therefore not in the qualified public graph. The explicit two-site counter
does not generalize arbitrary register-bank lowering. If the bank builds,
its first SRAM-only sequence is reset state, aligned word read/write, and
back-to-back transfers. Halfword access, controlled waits, and error
responses remain separate later claims. The retained evidence is
`qualification/mcu_ahb_constant_slave_evidence.jsonl`,
`qualification/mcu_bus_clock_evidence.jsonl`, and
`qualification/mcu_haddr5_logic_evidence.jsonl` plus
`qualification/mcu_haddr3_logic_evidence.jsonl`.
