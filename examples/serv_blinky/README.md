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
the retained route. A fresh source place-and-route with the pinned public
tools now builds, places, routes, and strict-bitgens release-strict end to
end, and the routed netlist passes `agamemnon build`'s `--verify` check. This
is a build-and-simulation result only: the fresh route it finds (3,027 data
PIPs, 0 unmapped/predicted/legacy selectors) has not been qualified on
silicon, and the command below remains a developer reproduction target, not
the release-supported `--template serv-blinky` scaffold (which continues to
strictly replay the retained, silicon-qualified checkpoint below):

```bash
agamemnon build examples/serv_blinky/serv_blinky.v --uarch \
  --pcf examples/serv_blinky/serv_blinky_L48.pcf \
  --freq 10 --verify --write-routed serv_blinky_routed.json \
  -o serv_blinky.bin
```

The retained strict route contains 2,186 data PIPs and no predicted, legacy,
or unresolved selector. Exact replay is release-supported and silicon-
qualified; a fresh source build finds a different, legal route (byte
identity with the retained route is not expected or required) that is
release-strict-clean and sim-verified, but not yet silicon-qualified.

## Run on L48

The table below is an explicit example-specific jumper plan, not the recovered
fixed Pico harness map. In that fixed harness GP0 reaches PIN_12 and GP4 reaches
PIN_10; this example deliberately adds or moves the GP0-to-PIN_10 reset jumper.

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
