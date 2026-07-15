# Collision-free three-lane serial merger

This hardware demo combines three idle-high UART lines onto one output. When
only one sender is active, logical AND forwards that sender exactly. The Pico
fixture schedules `A`, then `B`, then `C`, so PIN_16 reads `ABCABC...`.

This is deliberately **not a buffered UART arbiter**. Frames must not overlap;
overlap is an electrical/protocol collision. That limit reflects the currently
qualified routing state instead of hiding it behind an overstated demo.

## Build and simulate

From the repository root:

```bash
iverilog -g2005 -o serial_mux.vvp \
  examples/serial_mux/tb_serial_mux.v examples/serial_mux/serial_mux.v
vvp serial_mux.vvp

agamemnon build examples/serial_mux/serial_mux.v --uarch \
  --pcf examples/serial_mux/serial_mux_L48.pcf --verify \
  -o serial_mux.bin
```

The design is combinational, so it has no internal clock timing target. The
build must report 24/24 mapped data PIPs and zero predicted, legacy, or unmapped
selectors.

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

Either copy `pico_sender.py` to a MicroPython Pico, or use the AG32-Docs Pico
fixture command:

```text
UARTMUX 4096 24414 1 scheduled
```

The release qualification completed 4,096/4,096 exact `ABC` transactions on
silicon. The checked-in SRAM stub restores the PLL selected by the bitstream
after conservative HSI-rate configuration; it does not leave the fabric on HSI.

## For IceStorm users

Think of `serial_mux_L48.pcf` as the package constraint file and `--uarch` as
the nextpnr architecture selection. Unlike an iCE40 flow, the recovered AG32
database is silicon-evidence-gated. A route completing is necessary but is not
yet proof that every stateful path conducts; this example stays entirely on the
four combinational pad paths that have direct hardware evidence.
