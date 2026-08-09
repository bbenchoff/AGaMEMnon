# SERV CPU blinky

This example runs the SERV bit-serial RISC-V core with a true-dual-port 512x2
BRAM register file. Its program repeatedly executes `addi x1,x1,1` and
`sw x1,0(x0)`. A registered program-address bit drives L48 PIN_25, so the LED
changes only while instruction fetch continues.

The workload covers sustained fetch, decode, write-back, stores, and
simultaneous BRAM read/write-port use. It is not a complete RISC-V compliance
test. The broader qualified instruction signature is documented under
`qualification/`.

## Simulate

```bash
iverilog -g2005 -I examples/serv_blinky -o serv_blinky.vvp \
  examples/serv_blinky/tb_serv_blinky.v \
  examples/serv_blinky/serv_blinky.v
vvp serv_blinky.vvp
```

Expected result:

```text
PASS: 30 PC-bit LED toggles from 7768 fetches and 3883 stores
```

## Build status

The retained L48 routed artifact is available as an exact, hash-bound project
profile and is replayed by the hardware-free evidence gate:

```bash
agamemnon new serv-demo --template serv-blinky --board ag32vf303-l48
cd serv-demo
agamemnon build

# Maintainer evidence check from the repository root:
python qualification/regen_serv_evidence.py
```

The template and gate verify every public source/route hash and strictly repack
the retained route. A fresh source place-and-route with the pinned public tools
currently fails closed because the synthesized design cannot be placed
entirely in the qualified direct-D site pool. The command below is therefore a
developer reproduction target, not a release-supported source build:

```bash
agamemnon build examples/serv_blinky/serv_blinky.v --uarch \
  --pcf examples/serv_blinky/serv_blinky_L48.pcf \
  --freq 10 --verify --write-routed serv_blinky_routed.json \
  -o serv_blinky.bin
```

The retained strict route contains 2,186 data PIPs and no predicted, legacy,
or unresolved selector. Exact replay is release-supported; it does not make a
new source placement reproducible.

## Run on L48

Connect a common ground:

| Pico | AG32 L48 | Purpose |
|---|---|---|
| GP0 | PIN_10 | active-high reset/halt input |
| GP12 | PIN_25 | CPU progress output and onboard LED |

```bash
agamemnon sram .tmp/clkcfg_stub.bin --fabric serv_blinky.bin
```

With reset low, the onboard LED blinks. Holding reset high freezes execution
and holds the output low. The SRAM command is volatile.

Build `.tmp/clkcfg_stub.bin` using the command in
[examples/firmware/README.md](../firmware/README.md).

The pin mapping is specific to the `AGRV2KL48` qualification board.

## Register-file requirement

SERV can write back while reading an operand. A shared-address BRAM wrapper
corrupts legitimate collisions. `serv_rf_ram_dp` maps writes to Port A and
reads to Port B, matching SERV's required access pattern.

AGaMEMnon supports this exact x2 Port-B corridor. Other BRAM widths, tiles,
arbitrary placement, initialization layouts, and collision modes are outside
the supported BRAM boundary.
