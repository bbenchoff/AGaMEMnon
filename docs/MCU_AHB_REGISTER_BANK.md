# MCU External AHB register bank

Status: the protocol core and C header generator are implemented and pass
hardware-free simulation. The full hard-port design is not yet approved for
hardware: simultaneous `HRDATA[31:0]`, `HREADYOUT`, and `HRESP` packing remains
a known strict-flow source/path-allocation gap, and no live MCU transaction has
qualified this endpoint.

`agamemnon/rtl/mcu_ahb_register_bank.v` contains two layers:

- `agamemnon_ahb_register_bank`, a vendor-independent AHB-Lite protocol core;
- `agamemnon_mcu_ahb_register_bank`, which binds that core to the recovered
  typed AG32 External AHB port.

The default register map is:

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

Next experiment: replace the greedy response-source allocation with a bounded
joint allocator, then strict-build the complete wrapper. Only after that passes
should the L48 run an SRAM-first firmware sequence with timeouts and a reset
recovery path.

Time-box record: a fresh full-port strict build was stopped after 180 seconds
without a routed result. No further seeds were attempted; this item is deferred
until the allocator can reserve the response controls and 32 data lanes as one
joint problem.
