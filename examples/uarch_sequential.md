# Sequential RTL with `agrv2k`

`examples/designs/counter_ahb.v` is a four-bit counter observed through the MCU
External-AHB read path.

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
```

Outputs:

```text
counter.bin       uncompressed SRAM image
counter.bin.comp  compressed flash image
counter_routed.json
```

Run the verifier independently or compare an observed value set:

```bash
agamemnon verify counter_routed.json --cycles 96
agamemnon verify counter_routed.json --observed 0,1,2,3
```

The verifier models placed LUT INITs, routed LUT/flip-flop connectivity, carry
connections, and MCU read-lane binding. `SOUND` means every supplied hardware
value is reachable in the routed model. This is a design check, not electrical
qualification of a new route.

## Ordinary sequential RTL

```bash
agamemnon build design.v --uarch --freq 25 --verify -o design.bin
```

The backend packs registered logic, binds the MCU edge, places connected logic
regionally, splits high-fanout nets when needed, routes with router2, and
applies conservative timing. Strict bitgen rejects unresolved selectors.

## Dedicated carry

```bash
agamemnon build design.v --uarch --hard-carry --verify -o design.bin
```

Each chain receives one physical seed and contiguous arithmetic stages.
Multiple same-tile chains require:

```text
sum(stages) + number of chains <= 9
```

One chain may use the qualified 33-site, three-tile order for up to 32
arithmetic stages. Other spill locations, multiple long chains, branches, and
malformed chains fail closed.

The complete feature boundary is in [docs/STATUS.md](../docs/STATUS.md).
