# Three-lane serial multiplexer

This example receives three simultaneous 9,600-baud 8N1 streams, buffers one
completed byte per lane, and transmits the bytes in registered round-robin
order at 115,200 baud. The fixture sends `A`, `B`, and `C`; the output is
`ABCABC...`.

Each lane has one byte of elastic buffering. A sender must not complete a
second byte on a lane before the first has been accepted by the scheduler.

## Simulate and build

```bash
iverilog -g2005 -DSIMULATION -o serial_mux.vvp \
  examples/serial_mux/tb_serial_mux.v examples/serial_mux/serial_mux.v
vvp serial_mux.vvp

agamemnon build examples/serial_mux/serial_mux.v --uarch \
  --pcf examples/serial_mux/serial_mux_L48.pcf --freq 25 --verify \
  --write-routed serial_mux_routed.json -o serial_mux.bin
```

Expected simulation result:

```text
PASS: 24 overlapping input frames buffered in round-robin order
```

The strict route contains 2,281 data PIPs, including 17 dedicated-carry links
in the baud accumulator, and contains no predicted, legacy, or unresolved
selector. It does not require a qualified checkpoint.

## L48 wiring

Connect a common ground:

| Pico | AG32 L48 | Direction |
|---|---|---|
| GP0 | PIN_10 | Pico to AG32, lane A |
| GP1 | PIN_11 | Pico to AG32, lane B |
| GP5 | PIN_15 | Pico to AG32, lane C |
| GP6 | PIN_16 | AG32 merged output to Pico |

Load the volatile design:

```bash
agamemnon sram .tmp/clkcfg_stub.bin --fabric serial_mux.bin
```

Build `.tmp/clkcfg_stub.bin` using the command in
[examples/firmware/README.md](../firmware/README.md).

Run the host checker against the Pico fixture:

```bash
python examples/serial_mux/verify_hardware.py COM6 --frames 100
```

The fixture must generate and sample the 115,200-baud stream with fractional
timing; integer-microsecond bit periods are not accurate enough. The bundled
verifier includes raw-trace decoding for diagnosis.

These physical pins are specific to `AGRV2KL48`. The example exercises
qualified physical inputs, two-stage synchronizers, registered logic,
dedicated carry, and a physical output.
