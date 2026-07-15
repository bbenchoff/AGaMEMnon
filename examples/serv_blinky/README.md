# SERV CPU blink demo

This example is a hardware-qualified SERV bit-serial RISC-V system. SERV runs
an aliased two-instruction program (`addi x1,x1,1` and `sw x1,0(x0)`), uses an
inferred true dual-port 512x2 BRAM register file, and drives PIN_16 from a
registered program-address bit. A changing output therefore proves continuing
instruction fetch progress; it is not an unrelated heartbeat counter.

The program intentionally stays small. It proves sustained fetch, decode,
write-back, stores, and simultaneous BRAM read/write-port use, but it is not a
RISC-V compliance test and does not establish every SERV instruction or trap.

## Simulate

From the repository root:

```bash
iverilog -g2005 -I examples/serv_blinky -o serv_blinky.vvp \
  examples/serv_blinky/tb_serv_blinky.v \
  examples/serv_blinky/serv_blinky.v
vvp serv_blinky.vvp
```

The current testbench reports:

```text
PASS: 30 PC-bit LED toggles from 7768 fetches and 3883 stores
```

## Build

```bash
agamemnon build examples/serv_blinky/serv_blinky.v --uarch \
  --pcf examples/serv_blinky/serv_blinky_L48.pcf \
  --freq 10 --verify --write-routed serv_blinky_routed.json \
  -o serv_blinky.bin
```

The qualified route contains 2,177 data PIPs: 1,997 use conflict-free physical
selector evidence, 33 use unanimous tile-relative evidence, and none use a
legacy, predicted, or unresolved selector. Its post-route estimate is
27.91 MHz against the requested 10 MHz target.

## Run on the L48 board

Connect a common ground and wire:

| Pico | AG32 L48 | Purpose |
|---|---|---|
| GP0 | PIN_10 | reset; high halts, low runs |
| GP6 | PIN_16 | CPU program-address blink output |

Load the MCU clock/configuration stub and fabric image into SRAM:

```bash
agamemnon sram examples/firmware/clkcfg_stub.bin --fabric serv_blinky.bin
```

On the qualification board, reset high held GP6 low for 3,000/3,000 samples;
reset low produced 2,154 high and 5,846 low samples; reasserting reset again
held the output low for 3,000/3,000 samples. All programming was volatile.

PIN_16 is a header output, so connect an external LED with a suitable series
resistor or use a logic analyzer/Pico. The board LEDs are PIN_25–28. Dense SERV
routing to that left-edge bank is not yet qualified, so this example does not
claim to drive the onboard LEDs.

## Why the register file has two ports

SERV can write back while reading an operand. A shared-address BRAM wrapper
therefore corrupts legitimate collisions even if a tiny program happens to
survive them. `serv_rf_ram_dp` maps writes to Port A and reads to Port B, so the
example exercises the architecture SERV actually requires.

For an IceStorm user, this is analogous to inferring a dual-port `SB_RAM40_4K`,
but AGaMEMnon additionally restricts the hard-block corridors to selector and
conduction evidence recovered for this device. The successful build and the
hardware observation are both part of the qualification claim.
