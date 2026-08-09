# Command-line usage

Install the package from the repository:

```bash
pip install -e .
agamemnon --help
```

`python -m agamemnon.cli` is equivalent to `agamemnon`. Python-only commands
require Python 3.8 or newer. `build` also requires Yosys and the packaged
nextpnr overlay. SWD/DAP commands require CMSIS-DAP and AGaMEMnon's qualified
OpenOCD:

```text
agamemnon install-openocd
agamemnon doctor --probe-dap
```

Start with the release-supported, fabric-free template:

```text
agamemnon --version
agamemnon doctor
agamemnon new hello --board ag32vf303-l48 --template mcu-blink
```

See [INSTALLATION.md](INSTALLATION.md) and [PROJECTS.md](PROJECTS.md).
When tagged SDK bundles are published, the same commands will diagnose their
installed tool versions and transport capabilities.

## Read-only qualification intake

```text
agamemnon qualify --artifact build/design.bin --output qualification-report.json
```

This captures the host-only doctor report, the versioned five-dimensional
support matrix, and SHA-256 hashes of supplied artifacts. Artifact labels are
relative or basename-only, and user-home paths in diagnostics and notes are
redacted as `<HOME>`, so the report can be shared without leaking workstation
identity. It does not open a target transport or write AG32 state. See
[QUALIFICATION_REPORT.md](QUALIFICATION_REPORT.md).

## Tool configuration

| Variable | Meaning |
|---|---|
| `AGAMEMNON_OSS` | OSS CAD Suite root used to find Yosys and its runtime |
| `AGAMEMNON_UARCH_NEXTPNR` | `nextpnr-generic` built with the `agrv2k` overlay |
| `AGAMEMNON_UARCH_NEXTPNR_RUNTIME` | optional runtime DLL directory for native nextpnr on Windows |
| `AGAMEMNON_OPENOCD` | explicit OpenOCD override; normally omit after `install-openocd` |
| `AGAMEMNON_OOCD_CFG` | alternate OpenOCD target configuration |
| `AGAMEMNON_OOCD_SCRIPTS` | OpenOCD script directory |
| `AGAMEMNON_DEVICE` | package name; default `AGRV2KL48` |
| `AGAMEMNON_DATA` | alternate chip-database directory for development |
| `AGAMEMNON_ENGINE` | alternate engine directory for development |
| `AGAMEMNON_SYSCLK` | fabric frequency override when `--freq` is omitted; default 10 MHz |
| `AGAMEMNON_HSE` | external crystal frequency in MHz |

Yosys and nextpnr run in separate child environments. OSS CAD Suite libraries
are removed before a separately built native nextpnr is launched, preventing
incompatible MinGW DLLs from shadowing its runtime. Every uarch build executes
`nextpnr --version` first and reports loader/ABI failure separately from a
routing failure.

## Build

```bash
agamemnon build design.v --uarch -o design.bin
```

The command runs Yosys, generates or reuses the filtered device database,
runs nextpnr, and invokes strict bitgen. It writes:

```text
design.bin       99,944-byte uncompressed SRAM image
design.bin.comp  compressed flash image
```

Common options:

| Option | Effect |
|---|---|
| `--pcf FILE` | apply package-specific `set_io <port> PIN_<n>` constraints |
| `--mcu` | expose the MCU/fabric bridge |
| `--leds` | expose characterized LED outputs |
| `--hard-carry` | lower eligible arithmetic into qualified dedicated carry |
| `--cap N` | placement density hint; default 5 |
| `--maxfo N` | fanout floor used by split-net retry |
| `--freq MHz` | set the emitted fabric PLL and require timing closure there |
| `--verify` | simulate the routed result |
| `--verify-cycles N` | simulation length for `--verify` |
| `--write-routed FILE` | retain placed/routed JSON |
| `--qualified-checkpoint FILE` | replay a matching qualified placement and restrict routing to its PIPs |
| `--pin BEL` | pin one generic slice, such as `X10Y4_SLICE0` |
| `--baseline FILE` | select an alternate tile-grid canvas; the preamble is regenerated |

Normal designs do not require a qualified checkpoint. Strict release builds
reject any configurable route without an accepted selector encoding and
remove the requested output on failure. `AGAMEMNON_DEBUG=1` prints the
offending routes. `AGAMEMNON_ALLOW_UNMAPPED=1` is a development escape hatch
and is not a supported release mode.

`--mcu` is visible for qualification and ongoing generic bridge work, but the
current `AGAMEMNON_MCU_ENTRY` option has not been admitted to release maturity;
`release-strict` therefore rejects it. The `mcu-fpga` project does not enable
that option. It replays a hash-bound, silicon-qualified L48 ID/scratch route,
and rejects any source, routed-netlist, board, device, or output-hash drift.

### External AHB constant slave

The silicon-qualified combinational endpoint is a direct strict build:

```bash
agamemnon build examples/designs/mcu_ahb_constant_slave.v --uarch \
  --write-routed constant_slave.json -o constant_slave.bin
```

It returns `0x4147414d` for reads and completes writes without changing that
value. It qualifies the simultaneous `HRDATA[31:0]`, `HREADYOUT`, and `HRESP`
response bundle. It does not itself qualify the sequential register bank,
bus clock, wait states, errors, or byte access. Separate L48 evidence qualifies
default-topology 10 MHz bus-clock delivery, four exact direct-D sites, a
16-bit LFSR, GPIO-fed synchronous reset-to-zero/re-arm, and isolated
HADDR[3]/HADDR[5] logic ingress. See
[MCU_AHB_REGISTER_BANK.md](MCU_AHB_REGISTER_BANK.md) and the retained records
under `qualification/`.

### Physical IO

```bash
agamemnon build examples/designs/comb.v --uarch \
  --pcf examples/constraints/comb_proven_L48.pcf -o comb.bin
```

The legal device names are `AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and
`AGRV2KQ32`; each has its own physical bond map. Only L48 is silicon-qualified.
Project builds select the device through `[project].device` (normally supplied
by the board definition); a one-off build with no project defaults to L48.
Qualified L48 inputs are PIN_10, PIN_11, PIN_15, and PIN_19. Qualified L48
outputs include PIN_25, PIN_26, PIN_27, and PIN_28. Other packages are marked
architecture-recovered and produce a warning rather than an implied hardware
claim.

### Inspecting images

```bash
agamemnon explain design.bin
agamemnon explain design.bin --json -o design.json
agamemnon diff before.bin after.bin
```

`explain` reports the actual source form/size/SHA-256, canonical uncompressed
SHA-256, named tile features, CRC validity, residual bits, and the recognized
generated preamble profile. `diff` retains source metadata for both inputs and
separates named feature changes
from unmapped byte changes and ignores the regenerated CRC unless `--crc` is
requested.

### Dedicated carry

```bash
agamemnon build arithmetic.v --uarch --hard-carry -o arithmetic.bin
```

Each independent chain receives one physical seed and contiguous stages.
Same-tile chains require `sum(stages) + chain_count <= 9`. One chain may use
the qualified 33-site corridor for up to 32 arithmetic stages. Unsupported
spill locations, multiple long chains, branches, and malformed chains fail.

### Timing and PLL

```bash
agamemnon build design.v --uarch --freq 25 -o design.bin
```

`--freq` is authoritative for both nextpnr timing and the PLL written into the
bitstream. It overrides `AGAMEMNON_SYSCLK`, preventing an image analyzed at one
frequency from running at another. When neither is supplied, both use the
qualified 10 MHz default. Timing uses conservative cell arcs and worst delays
per driving mux family, except for 542 certified local OMUX-to-IMUX pairs where
the decoded 0.401 ns slow-corner whole-pattern maximum is used. Missing,
ambiguous, four-node, hard-block, and non-routing entries keep the conservative
model; `AGAMEMNON_WIRE_TIMING_MARGIN` applies equally to exact and fallback
delays and cannot be set below 1.0. The exact subset is L48-scoped; other
package selections remain fully conservative. The report does not include exact native
wire classes, clock skew, IO, hard-block, package, or broad PVT timing.

Byte-exact supported `(--freq,AGAMEMNON_HSE)` pairs are `(100,8)`, `(50,8)`,
`(25,8)`, `(10,8)`, `(100,16)`, `(60,8)`, and `(100,12)` MHz. Other pairs fail
before synthesis. Support here means a complete vendor-preamble match; consult
[Status](STATUS.md) before treating a profile as silicon-qualified on a given board.

## Routed-netlist verification

```bash
agamemnon verify design_routed.json --cycles 64
agamemnon verify design_routed.json --observed 0,1,2,3
```

The verifier models placed LUT INIT values, routed LUT/flip-flop connectivity,
carry connections, and MCU read-lane binding. `--observed` checks that every
hardware value is reachable in simulation and reports observation coverage.
This does not replace silicon qualification of electrical paths.

## Bitstream commands

```bash
# Routed JSON to images, image to raw configuration
agamemnon pack design_routed.json design.bin
agamemnon unpack design.bin.comp -o raw.img

# LZW conversion
agamemnon decode fabric.bin -o raw.img
agamemnon encode raw.img -o fabric.bin

# Lossless named text
agamemnon to-agasc fabric.bin -o fabric.agasc
agamemnon from-agasc fabric.agasc -o rebuilt.bin
agamemnon from-agasc fabric.agasc --uncompressed -o rebuilt-raw.bin

# Edit one placed LUT
agamemnon edit-lut fabric.bin --le 20,12,1 --init 0x96e9 -o edited.bin
```

`.agasc` preserves mapped asserted features by name and unmapped asserted bits
as sparse `.raw` records. Assembly rejects unknown/duplicate features,
overlapping raw ranges, and raw writes to named bits. CRC is regenerated by
default.

## Hardware commands

The common commands select a transport consistently:

```text
agamemnon probe --transport dap
agamemnon probe --transport usb --port COM7
agamemnon probe --transport uart --port COM6

agamemnon backup full.bin --transport usb
agamemnon flash app.bin --addr 0x80010000 --backup full.bin --transport usb
agamemnon go 0x80010000 --transport usb
```

`dap` is the default. USB and UART writes require a complete backup. USB is not
a recovery transport because its uploader resides in main flash. UART is a
mask-ROM recovery transport but the current L48 board needs the hardware
change in [UART_BOOTLOADER.md](UART_BOOTLOADER.md).

```bash
agamemnon probe
agamemnon sram firmware.bin --fabric design.bin --words 10
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

`sram` loads firmware at `0x20000000`, fabric at `0x20002000`, resumes the
core, and reads result words from `0x20001000`. It does not write flash.

`flash` erases complete 4-KiB sectors, programs through the on-chip controller,
reads the region back, and compares the bytes. Preserve the decompressor when
updating the existing compressed layout.

`image` plans or writes MCU and uncompressed fabric regions:

```bash
agamemnon image --fabric design.bin --mcu firmware.bin
agamemnon image --fabric design.bin --mcu firmware.bin \
  --plan-json build/boot-plan.json
agamemnon image --fabric design.bin --mcu firmware.bin \
  --flash --backup full-flash.bin
```

Main-flash writes do not change the boot pointer. `--write-options` exposes an
explicitly unsupported option-byte pointer operation and requires both the
normal full-flash `--backup` and a separate 128-byte `--option-backup`.
Every `image --flash` operation requires the full-flash backup. Backup captures
are written to a temporary file, size-checked, and atomically published so a
failed capture cannot masquerade as a fresh backup.
`--plan-json` is hardware-free and records portable artifact labels, SHA-256
hashes, exact flash ranges, erase geometry, and the value/complement option
pointer pair. It can be retained as release provenance whether or not `--flash`
is requested.

Paths passed through OpenOCD are Tcl-quoted, including paths containing spaces.
The mask-ROM UART0 transport is available through the checked-in Pico 2 bridge:

```bash
agamemnon uart-probe --port COM6
agamemnon uart-backup full-flash.bin --port COM6
agamemnon uart-flash firmware.bin --addr 0x80000000 \
  --backup pre-write.bin --port COM6
agamemnon uart-reset --port COM6
```

`uart-flash` requires a complete pre-write backup, preserves bytes outside the
payload within every touched 4-KiB sector, verifies full-sector readback, and
resets into flash only after success. See [PROGRAMMING.md](PROGRAMMING.md) for
the Pico-to-LQFP48 wiring. Native USB DFU is not implemented.

Read [PROGRAMMING.md](PROGRAMMING.md) before a persistent write.

## Project run and serial monitor

```bash
agamemnon run --transport dap          # volatile SRAM execution of the current project
agamemnon run --transport usb --flash --backup full-flash.bin
agamemnon monitor --port COM7 --baud 115200
```

`run` executes the current project's built artifacts without naming them
manually. With the default `dap` transport it loads the MCU image (and the
fabric image when the project has one) through `sram`, so nothing is written
to flash; `--words` and `--sleep` pass through to the mailbox read. With
`--transport usb` it issues `GO` at the project's `mcu_address`, and
`--flash` first programs that image — which requires a complete `--backup`,
like every persistent write. The UART ROM transport is not supported by
`run`; use `uart-flash` for recovery. Project resolution and manifest fields
are described in [PROJECTS.md](PROJECTS.md).

`monitor` opens a plain serial terminal on `--port` at `--baud`
(default 115200), for firmware that prints over a USB/UART adapter.
