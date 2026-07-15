# AGaMEMnon command-line usage

Install the package from the repository:

```bash
pip install -e .
agamemnon --help
```

The equivalent invocation is `python -m agamemnon.cli`. Pure-software
commands need Python 3.8 or newer. `build` also needs Yosys and nextpnr.
Hardware commands need a CMSIS-DAP probe and a compatible OpenOCD binary with
AGM's `riscv -dap` target extension.

## Tool resolution

| Variable | Meaning |
|---|---|
| `AGAMEMNON_OSS` | oss-cad-suite root; `bin/yosys` and related tools are found here |
| `AGAMEMNON_UARCH_NEXTPNR` | `nextpnr-generic` built with the shipped `agrv2k` overlay |
| `AGAMEMNON_UARCH_NEXTPNR_RUNTIME` | optional directory containing the native nextpnr runtime DLLs, such as an MSYS2 `mingw64/bin` directory on Windows |
| `AGAMEMNON_OPENOCD` | compatible OpenOCD executable for hardware commands |
| `AGAMEMNON_OOCD_CFG` | alternate OpenOCD config; default is the packaged `agrv2k.cfg` |
| `AGAMEMNON_OOCD_SCRIPTS` | OpenOCD script directory when it cannot find `target/swj-dp.tcl` |
| `AGAMEMNON_DEVICE` | package name; default `AGRV2KL48` |
| `AGAMEMNON_DATA` | alternate chip-database directory for development |
| `AGAMEMNON_ENGINE` | alternate engine directory for development |

Yosys and nextpnr run in separate child environments. `AGAMEMNON_OSS/bin` and
`lib` are used for the oss-cad-suite tools but removed before launching a
separately built native nextpnr, preventing incompatible MinGW DLLs from being
loaded into `nextpnr-generic.exe`. On Windows, set
`AGAMEMNON_UARCH_NEXTPNR_RUNTIME` when that executable needs DLLs from its own
toolchain. Every uarch build runs `nextpnr --version` first and reports a loader
or ABI failure directly instead of misclassifying a crash as a route failure.

## `build`

The recommended release flow uses the `agrv2k` uarch:

```bash
agamemnon build design.v --uarch -o design.bin
```

It runs Yosys, creates or reuses the selector/conduction-gated device database,
runs nextpnr, and invokes strict bitgen. Output is:

```text
design.bin       99,944-byte uncompressed image for SRAM configuration
design.bin.comp  LZW-compressed image for flash
```

Useful options:

| Option | Effect |
|---|---|
| `--pcf FILE` | Apply `set_io <port> PIN_<n>` constraints; physical mapping is supported for L48 |
| `--mcu` | Expose the MCU/fabric bridge |
| `--leds` | Expose and pin the characterized LED pads |
| `--hard-carry` | Lower eligible arithmetic to the qualified same-tile Cin/Cout path |
| `--cap N` | Cells-per-tile hint used by placement and split-net retry; default 5 |
| `--maxfo N` | Tightest fanout floor for split-net escalation |
| `--freq MHz` | Request timing closure and fail if nextpnr misses it |
| `--verify` | Cycle-simulate the routed result and report MCU read values |
| `--verify-cycles N` | Simulation length for `--verify` |
| `--write-routed FILE` | Retain final placed/routed JSON |
| `--qualified-checkpoint FILE` | Replay a matching qualified placement and restrict routing to its PIPs |
| `--pin BEL` | Pin a single generic slice, for example `X10Y4_SLICE0` |
| `--baseline FILE` | Use an alternate bitstream canvas/preamble |

The checkpoint option is for exact qualification reproduction. Normal large
builds do not require a checkpoint.

Strict release builds expose only conflict-free physical or unanimous-relative
general-routing selectors. If a routed PIP lacks an exact encoding, bitgen
removes the requested output and exits nonzero. `AGAMEMNON_DEBUG=1` prints the
offending routes. `AGAMEMNON_ALLOW_UNMAPPED=1` is an archival development
escape hatch and must not be used for release or qualification artifacts.

### Physical IO

```bash
agamemnon build examples/designs/comb.v --uarch \
  --pcf examples/constraints/comb_proven_L48.pcf -o comb.bin
```

Package legality data exists for `AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and
`AGRV2KQ32`, but the physical bond map exists only for L48. A PCF build for
another package fails closed. The characterized L48 input pins are PIN10,
PIN11, PIN15, and PIN19; the tool does not infer qualification for other
banks.

### Dedicated carry

```bash
agamemnon build arithmetic.v --uarch --hard-carry -o arithmetic.bin
```

Every independent chain receives a physical head seed and contiguous slices.
Multiple chains are accepted when `sum(bits) + chains <= 9`, the largest
silicon-qualified same-tile footprint. Branches, malformed chains, larger
footprints, and inter-tile overflow fail immediately. Inter-tile carry spill
is not implemented.

### Timing and PLL

```bash
agamemnon build design.v --uarch --freq 48 -o design.bin
```

The current timing model uses conservative cell arcs and worst-case delays per
driving mux family. It does not include exact wire classes, clock skew, IO,
hard-block, or package timing, so `--freq` is a fail-closed estimate rather
than a complete silicon Fmax guarantee.

Clock generation uses `AGAMEMNON_SYSCLK` and `AGAMEMNON_HSE`, defaulting to
100 and 8 MHz. Supported byte-exact pairs are `(100,8)`, `(50,8)`, `(25,8)`,
`(10,8)`, and `(100,16)`. Other ratios fail before an output is written.

## Routed-netlist verification

```bash
agamemnon verify design_routed.json --cycles 64
agamemnon verify design_routed.json --observed 0,1,2,3
```

The verifier simulates placed slice INIT values, actual routed inputs/Q
connectivity, carry behavior, and MCU_DOUT binding. `--observed` checks that
hardware values are sound with respect to reachable simulated values and
reports coverage. It is an offline structural/behavioral check, not a
substitute for silicon routing qualification.

## Bitstream commands

### Routed JSON to image

```bash
agamemnon pack design_routed.json design.bin
agamemnon unpack design.bin.comp -o raw.img
```

`pack` writes the uncompressed output path and a `.comp` image beside it.
`unpack` writes the fixed 99,936-byte raw configuration.

### LZW codec

```bash
agamemnon decode fabric.bin -o raw.img
agamemnon encode raw.img -o fabric.bin
```

The compressed format is an 8-byte device header followed by variable-width
LZW. `decode`/`encode` round-trip canonical images byte-for-byte.

### `.agasc`

```bash
agamemnon to-agasc fabric.bin -o fabric.agasc
agamemnon from-agasc fabric.agasc -o rebuilt.bin
agamemnon from-agasc fabric.agasc --uncompressed -o rebuilt-raw.bin
```

`.agasc` names mapped asserted features by tile and preserves unmapped asserted
state in sparse `.raw` records. Assembly rejects unknown/duplicate features,
overlapping raw ranges, and raw writes to named bits. CRC is regenerated by
default.

### LUT editing

```bash
agamemnon edit-lut fabric.bin --le 20,12,1 --init 0x96e9 -o edited.bin
```

This changes the 16-bit truth table of one placed LUT without routing the
design again.

## Hardware commands

```bash
agamemnon probe
agamemnon sram firmware.bin --fabric design.bin --words 10
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

`sram` loads firmware at `0x20000000`, fabric at `0x20002000`, runs the core,
and reads results from `0x20001000`. It does not write flash.

`flash` erases full 4-KiB sectors, programs through the open flash-controller
implementation, reads the region back, and compares it byte-for-byte. Preserve
the decompressor when updating the existing compressed factory layout.

`image` plans or writes MCU and uncompressed fabric regions:

```bash
agamemnon image --fabric design.bin --mcu firmware.bin
agamemnon image --fabric design.bin --mcu firmware.bin \
  --flash --backup full-flash.bin
```

Writing those regions does not change the boot pointer. `--write-options`
attempts an option-byte pointer update, but that operation remains explicitly
unverified and requires a backup. UART and USB transports are not implemented.

See [PROGRAMMING.md](PROGRAMMING.md) before any persistent write.
