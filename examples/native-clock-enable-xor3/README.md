# Native enable packing example

This ordinary-source AHB datapath holds an eight-bit register when its enable
is low. Each new data bit is a three-input XOR. Native clock enable lets the
data LUT and register share one slice; lowering the hold condition into data
logic needs another LUT per bit in this example.

From the repository root, with the current `agrv2k` nextpnr installed:

```sh
agamemnon build examples/native-clock-enable-xor3/open_top.v --top top --uarch --cap 16 --freq 10 --attempt-timeout 20 --write-routed native.json -o native.bin
agamemnon build examples/native-clock-enable-xor3/open_top.v --top top --uarch --cap 16 --freq 10 --attempt-timeout 20 --no-native-clock-enable --write-routed data.json -o data.bin
python examples/native-clock-enable-xor3/compare.py data.json native.json
```

The source is retained verbatim from the qualification fixture. The fixed MCU
reset endpoint is part of the public bus wrapper; fabric slices have no BEL
constraints or route replay. The source has 44 registers overall, eight using
native enable. Synchronous-reset state uses data logic.

The measured pair uses 77 slices with data-logic enables and 69 with native
enables: **8 slices saved (10.4%)**. The native computed-LUT image passed three
control-first silicon runs, each checking all 256 input bytes during enabled
updates and disabled holds, plus scratch and free-running-state observations.
The reported routing-model Fmax was 109.49 versus 115.43 MHz; silicon was tested
at 10 MHz. This is a packing result for this datapath, not a measured silicon
speed improvement or a general capacity guarantee. See the
[qualification scope](../../docs/NATIVE_CLOCK_ENABLE_EXPERIMENT.md).

Occupied tiles increased from 17 to 19: isolation and placement still leave
unused slice slots. Fewer slices therefore does not mean this run occupied a
smaller physical region.

Native placement can still fail for other sources. The default build then
retries data-logic enables when the entire native ladder fails at placement.
Check the actual routed native-register count when comparing results: a build
that fell back cannot demonstrate a native packing benefit.
