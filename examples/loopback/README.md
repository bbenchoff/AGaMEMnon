# loopback — the "both halves work" example

The AG32 "hello world": the MCU drives GPIO bits out, through a fabric inverter, and reads
them back. It exercises the whole hybrid: RISC-V firmware + a real FPGA bitstream + the MCU↔fabric
edge — and it's the first thing that was proven on silicon.

```
MCU GPIO4.1 (out) ──► fabric LUT inverter ──► GPIO4.2 (in)  ─┐
MCU GPIO4.3 (out) ──► fabric LUT inverter ──► GPIO4.4 (in)  ─┴─► MCU reads: dout == ~din
```

## The two halves

- **Fabric** (`examples/designs/mcu_loop2.v`): a 2-bit loopback — each MCU `din` bit routed through
  a LUT4 inverter to a `dout` bit. Build it with AGaMEMnon from the repo root:
  ```bash
  agamemnon build examples/designs/mcu_loop2.v -o mcu_loop2.bin --mcu   # → uncompressed fabric image
  ```
- **Firmware** (`loopback_readback.c`): brings up clocks, sets GPIO4 (bits 1,3 out; 2,4 in), sweeps
  the four input combinations, and stores `(din,dout)` results to SRAM `0x20001000`. It assumes the
  fabric is **already configured** (by flash-boot, or by an SRAM-inject config step) — so it only
  reads FCB status and runs the loopback; it does not itself stream the bitstream.

## Run it — SRAM-inject (bench, volatile)

Load the fabric image to SRAM, let a stub `ag32_fcb_config()` it, then run this firmware and read
back the result over SWD. (Uses `agamemnon` SRAM-inject; needs only generic RISC-V debug.)

Expected: `FCB STAT = 0x000f0002`, and `dout = ~din` on all four combos.

## Run it — flash-boot (persistent, no debugger)

Flash the fabric bitstream so the boot ROM configures it at power-on (see `../../docs/PROGRAMMING.md`
for the recipe + the sector-erase gotcha), leave a minimal MCU image (or this readback firmware) at
`0x80000000`, power-cycle, and the loopback runs with nothing attached. This is the milestone flash-
boot path — an open bitstream booting itself.

## Note

`loopback_readback.c` is the exact firmware used to validate flash-boot on silicon. The pin mapping
(GPIO4.1/3 out, 4.2/4 in) matches the `mcu_loop2` fabric design; if you rebuild the fabric with
different pins, match them here.
