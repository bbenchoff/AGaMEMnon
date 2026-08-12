# MCU External-AHB soft UART

Status: build- and simulation-supported; L48 route and silicon qualification
remain open.

`agamemnon/rtl/mcu_ahb_soft_uart.v` provides an 8-N-1 UART as an alternative
occupant of the qualified 16-byte External-AHB register window. It deliberately
replaces the ID/scratch/counter/W1C bank rather than claiming that both fit in
the same routed image. The protocol core and hard-port wrapper are separate so
the behavior remains testable without AG32 primitives.

The default divisor is 87 clocks per bit, approximately 115200 baud at the
qualified 10 MHz default bus clock. The divider is fixed at synthesis time.

| Offset | Name | Access | Meaning |
|---:|---|---|---|
| `0x0` | `TXDATA` | write | Low byte launches one frame; a write while busy fails with `HRESP` |
| `0x4` | `RXDATA` | read | Low byte is the received value; the completing read acknowledges RX state |
| `0x8` | `STATUS` | read | Bit 0 TX busy, bit 1 RX valid, bit 2 framing error, bit 3 overrun |
| `0xc` | `DIVISOR` | read | Fixed clocks-per-bit value |

Only aligned 32-bit SINGLE transfers are accepted. Misaligned, subword,
non-SINGLE, out-of-window, unknown-register, and read-only writes complete with
`HRESP` and cannot launch a frame. `IRQ` follows RX-valid. Reset is synchronous
to `HCLK`; the hard `MCU_RESETN` route remains outside the qualified claim.

The pinned simulator regression loops TX back into the synchronized RX input,
transmits the same byte twice, acknowledges each receive, rejects a second
write while busy without disturbing the active frame, and checks the
fail-closed transfer classes. Passing simulation is not electrical or silicon
qualification of TXD, RXD, IRQ, baud rate, or the hard-port wrapper.
