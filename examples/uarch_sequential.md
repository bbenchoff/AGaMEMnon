# Sequential RTL with the `agrv2k` backend

`examples/designs/counter_ahb.v` is a four-bit counter whose exposed bits are
returned through the MCU External-AHB read path. Observing every reachable read
value proves multi-bit registered state and the MCU_DOUT lane binding.

Build it with the release backend and retain the routed netlist:

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
```

The command performs Yosys mapping, uarch pack/place/route, strict bitgen, and
routed-netlist simulation. It writes:

```text
counter.bin       uncompressed SRAM image
counter.bin.comp  compressed flash image
counter_routed.json
```

Run the verifier again or compare a hardware observation set:

```bash
agamemnon verify counter_routed.json --cycles 96
agamemnon verify counter_routed.json --observed 0,1,2,3
```

The verifier uses placed LUT INITs, routed slice inputs/Q, carry connections,
and MCU_DOUT lane names. `SOUND` requires every observed hardware value to be
reachable in simulation; coverage reports how much of the simulated set was
observed. This check detects a scrambled read binding or structurally wrong
routed design, but it does not replace silicon qualification of routing.

## What the backend handles

The `agrv2k` uarch loads a selector/conduction-gated device database, packs
registered feedback, binds the MCU edge, places connected logic in a compact
conducting region, routes with nextpnr router2, and applies conservative timing
arcs. The default density cap is 5. If an unsplit route fails, the CLI retries
across density/fanout settings without accepting unresolved bitgen selectors.

For ordinary sequential RTL:

```bash
agamemnon build design.v --uarch --freq 25 --verify -o design.bin
```

For qualified same-tile dedicated carry:

```bash
agamemnon build design.v --uarch --hard-carry --verify -o design.bin
```

Hard-carry chains receive one physical head seed per independent chain and
contiguous slices in the qualified tile. The release limit is nine occupied
slots total (`sum(arithmetic bits) + number of chains <= 9`): one eight-stage
chain and two independent three-stage chains have passed on silicon.
Inter-tile spill is not implemented.

## Current evidence

The backend passes a 72-design randomized matrix covering independently seeded
16/32/64-bit LFSR, xorshift, and nonlinear mixed machines. Fresh xorshift64 and
mixed64 images have produced the predicted states on silicon.

The current SERV example builds without a checkpoint, uses a true dual-port x2
BRAM register file, and passes both routed-netlist simulation and reset/run/reset
hardware qualification. Its program-address output toggled across 8,000 Pico
samples while reset held it low before and after the run. The workload is an
aliased `addi`/`sw` loop; broader instruction and trap compliance remains open.

The remaining limits are described in `docs/STATUS.md`: inter-tile carry,
general BRAM Port-B corridor selection and narrow initialization, full-width MCU transfers,
broader package/IO and PLL coverage, and exact timing classes/skew.
