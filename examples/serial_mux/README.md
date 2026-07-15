# Buffered three-lane serial multiplexer

This hardware demo receives three simultaneous 9,600-baud 8N1 streams, keeps
one completed byte in an elastic buffer per lane, and transmits the bytes in
registered round-robin order at 115,200 baud. The Pico sends `A`, `B`, and `C`
at the same time, and L48 PIN_16 produces `ABCABC...` without input-frame
collisions.

The buffers absorb one complete byte per input. They are not unbounded FIFOs:
software must not deliver a second completed byte on one lane before its first
byte has been accepted by the scheduler.

## Build and simulate

From the repository root:

```bash
iverilog -g2005 -o serial_mux.vvp \
  examples/serial_mux/tb_serial_mux.v examples/serial_mux/serial_mux.v
vvp serial_mux.vvp

agamemnon build examples/serial_mux/serial_mux.v --uarch \
  --pcf examples/serial_mux/serial_mux_L48.pcf --freq 25 --verify \
  --write-routed serial_mux_routed.json \
  -o serial_mux.bin
```

The qualified route contains 2,281 data PIPs: 2,264 configurable routes plus
17 dedicated-carry links in the baud NCO. It uses 156 registered slices,
closes the requested 25 MHz target at an estimated 32.22 MHz, and reports zero
predicted, legacy, or unmapped selectors. Simulation must report:

```text
PASS: 24 overlapping input frames buffered in round-robin order
```

## Hardware

Connect a common ground, then:

| Pico | AG32 L48 | Direction |
|---|---|---|
| GP0 | PIN_10 | Pico to AG32, lane A |
| GP1 | PIN_11 | Pico to AG32, lane B |
| GP5 | PIN_15 | Pico to AG32, lane C |
| GP6 | PIN_16 | AG32 merged output to Pico |

Load the volatile fabric image:

```bash
agamemnon sram examples/firmware/clkcfg_stub.bin --fabric serial_mux.bin
```

Run the checked-in host verifier against a Pico using the current AG32-Docs
fixture firmware:

```bash
python examples/serial_mux/verify_hardware.py COM6 --frames 100
```

The release qualification used a fractional-Q16 Pico transmitter/receiver and
completed 4,096/4,096 exact simultaneous `ABC` transactions on silicon. An
older integer-microsecond fixture rounded the 115,200-baud output bit period
and could report false framing errors; use the current fixture or the raw-trace
decoder in `verify_hardware.py`. The checked-in SRAM stub restores the PLL
selected by the bitstream after conservative HSI-rate configuration.

These physical pins are the `AGRV2KL48` package mapping. No physical mapping is
claimed for L100, L64, or Q32.

## For IceStorm users

Think of `serial_mux_L48.pcf` as the package constraint file and `--uarch` as
the nextpnr architecture selection. Unlike an iCE40 flow, the recovered AG32
database is silicon-evidence-gated. This example exercises qualified physical
inputs, explicit two-stage synchronizers, registered logic, dedicated carry,
and a physical output; a successful route alone would not establish that
hardware result, so the exact artifact hashes are retained in
`qualification/example_evidence.jsonl`.
