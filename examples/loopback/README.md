# MCU/fabric loopback

This example drives MCU GPIO signals into fabric LUT inverters and reads the
results back through the MCU/fabric bridge.

```text
MCU output -> fabric LUT inverter -> MCU input
```

## Build the fabric

```bash
agamemnon build examples/designs/mcu_loop2.v --uarch --mcu -o mcu_loop2.bin
```

`examples/designs/mcu_loop2.v` implements two independent inversions.

## Build the firmware

`loopback_readback.c` configures GPIO4, sweeps the input combinations, and
stores `(din,dout)` observations at SRAM address `0x20001000`. It expects the
fabric to be configured by the SRAM loader or power-on boot.

Use the linker and compiler recipe in [../firmware/README.md](../firmware/README.md).

## Run from SRAM

```bash
agamemnon sram loopback_readback.bin --fabric mcu_loop2.bin --words 10
```

Expected FCB status is `0x000f0002`; each observed output is the complement of
its input. This path is volatile and does not modify flash.

## Persistent boot

The supported persistent recipe replaces the compressed fabric image at the
board's existing option pointer while preserving the decompressor sector.
Back up the complete flash and power-cycle after programming. See
[docs/PROGRAMMING.md](../../docs/PROGRAMMING.md).
