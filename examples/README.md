# Examples

These examples use the public AGaMEMnon CLI. None invokes a vendor executable.

## Prerequisites

- Install AGaMEMnon with `pip install -e .`.
- Build and select the `agrv2k` nextpnr backend for RTL examples.
- Install Icarus Verilog to run the included RTL testbenches.
- Use `pip install -e ".[examples]"` for the serial-mux host verifier.
- Hardware commands require an L48 board, CMSIS-DAP, and compatible OpenOCD.

## Bitstream recipes

`01_roundtrip.sh` and `01_roundtrip.ps1` decode a fabric `.bin` to its
99,936-byte raw image, encode it again, and compare canonical output.

```bash
./examples/01_roundtrip.sh
```

`02_edit_lut.sh` changes the truth table of placed LE `(20,12,1)` without
rerouting and reports the raw bytes affected.

```bash
./examples/02_edit_lut.sh
```

`03_flash_and_verify.sh` is a manually enabled persistent-write recipe. Read
the script and [programming guide](../docs/PROGRAMMING.md) first. It backs up
the complete flash, writes the configured region, and verifies readback.

## RTL examples

`designs/` contains small combinational, sequential, MCU-edge, carry, and
physical-IO designs. PCFs are under `constraints/`.

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
```

See [uarch_sequential.md](uarch_sequential.md) for routed-netlist verification
and dedicated-carry use.

## MCU/fabric loopback

`loopback/` and `firmware/` exercise the MCU GPIO bridge through fabric LUTs.
The volatile recipe loads both images through SRAM and reads observations over
SWD. See [loopback/README.md](loopback/README.md).

## SERV blinky

`serv_blinky/` runs SERV with a true-dual-port x2 BRAM register file. A
registered program-address bit drives L48 PIN_25, so the LED changes only while
the CPU continues fetching. The design builds through strict P&R without a
checkpoint. See [serv_blinky/README.md](serv_blinky/README.md).

## Serial multiplexer

`serial_mux/` receives simultaneous 9,600-baud 8N1 streams on L48
PIN_10/11/15, buffers one completed byte per lane, and transmits their
round-robin merge at 115,200 baud on PIN_16. See
[serial_mux/README.md](serial_mux/README.md).

Physical pin claims in these examples are specific to `AGRV2KL48` and the
documented board wiring.
