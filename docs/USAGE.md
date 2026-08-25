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

> [!IMPORTANT]
> A successful build is not a general silicon guarantee. The 105-design
> campaign found 52 no-image outcomes and 13 cleanly emitted correctness
> escapes. Use `--release-strict` for the tightest selector boundary, inspect
> the confidence/pack reports, and treat only the exact profiles in
> [STATUS.md](STATUS.md) as silicon-qualified. Release-strict refuses known
> typed SPI MISO and affected initialized-BRAM surfaces, but not every possible
> wrong composition is recognizable yet.

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
| `--release-strict` | expose only tier-1 witnessed routing admissions; this is the tightest selector gate, not a universal functional proof |
| `--hard-carry` | compatibility spelling for the default qualified carry allocation |
| `--no-hard-carry` | force all arithmetic through the ordinary LUT path |
| `--research-unsafe` | opt into recovered/vendor-derived/conflicted/predicted routing data and require a provenance sidecar |
| `--cap N` | placement density hint; default 5 |
| `--maxfo N` | fanout floor used by split-net retry |
| `--compact-maxd N` | experimental regional-placement Manhattan radius; no default |
| `--freq MHz` | set the emitted fabric PLL and require timing closure there |
| `--verify` | simulate the routed result |
| `--verify-cycles N` | simulation length for `--verify` |
| `--write-routed FILE` | retain placed/routed JSON |
| `--qualified-checkpoint PROFILE` | select a hash-bound exact replay. Source/checkpoint hashes, L48 HSE/SYSCLK, primitive graph, BEL/routes and final raw/compressed hashes must all match; profiles implicated by an open correctness defect refuse |
| `--qualified-bram-write PROFILE` | with `build --uarch`, select an exact X13Y4 x18 source profile. The two `i0-d1` profiles remain replayable; the two initialized `i1-d0` read profiles now fail closed under `VP-AGM-006` |
| `--pin BEL` | pin one generic slice, such as `X10Y4_SLICE0` |
| `--baseline FILE` | select an alternate tile-grid canvas; the preamble is regenerated |

Normal designs do not require a qualified checkpoint. Strict release builds
reject any configurable route without an accepted selector encoding and
remove the requested output on failure. The registered replay profiles are
source-tree qualification fixtures, not portable project templates or a
generic routing escape hatch. `AGAMEMNON_DEBUG=1` prints the
offending routes. `AGAMEMNON_ALLOW_UNMAPPED=1` is a development escape hatch
and is not a supported release mode.

Qualified-checkpoint replay is deliberately exact: changed LUT INITs, primitive
parameters, ports, cells, or connections are rejected. Net names and JSON bit
IDs may differ because the proof matches complete driver/sink signatures. The
mode bypasses nextpnr only after that proof, then runs the ordinary strict
bitstream checker. It cannot be combined with `--research-unsafe`.

The bounded BRAM source surface supports exact checkpoint replay and an
explicit source-to-route build only where the later correctness campaign did
not invalidate the profile. Replay remains available for the high-data arm:

```powershell
agamemnon pack agamemnon/sdk/qualified_bram_tmux9/bram_tmux9_i0_d1_we1_routed.json bram-write.bin `
  --qualified-checkpoint bram-tmux9-i0-d1-we1
```

The other previously retained profile IDs are `bram-tmux9-i0-d1-we0`,
`bram-tmux9-i1-d0-we0`, and `bram-tmux9-i1-d0-we1`. The two `i0-d1` profiles
still reproduce their exact outputs. The two `i1-d0` initialized-read profiles
now refuse because independent x1/x18 campaign vehicles read zero even though
the currently modeled INIT/config surface was exact (`VP-AGM-006`). This is a
fail-closed correction to the old four-profile claim, not a repaired BRAM read
path. A fresh source build of the remaining high arm is:

```powershell
agamemnon build agamemnon/sdk/qualified_bram_tmux9/bram_tmux9_i0_d1_we1.v `
  --uarch --qualified-bram-write bram-tmux9-i0-d1-we1 -o bram-write.bin
```

The INIT=1 provenance files remain checked in for diagnosis, but the affected
profiles do not emit images. This does not qualify editing either source,
inferred/generic BRAM writes, other addresses, widths, ports, sites, modes,
clocks, output corridors, or schedules.

`--mcu` is visible for qualification and ongoing generic bridge work, but the
current `AGAMEMNON_MCU_ENTRY` option has not been admitted to release maturity;
`release-strict` therefore rejects it. The `mcu-fpga` project does not enable
that option. It replays the hash-bound, silicon-qualified exact L48 public32
map and rejects any source, routed-netlist, board, device, or output-hash drift.
The default exact profile returns canonical ID32
`0x4147414d` and zero-extends scratch16/counter3/W1C1 on raw word reads. It is
one four-word L48 composition, not a generic register-bank generator.

In the current checkout, the public32 composer/checker intentionally reports
`candidate hash does not match reviewed artifact`. Follow
[LANDING_A_CHIPDB_CHANGE.md](LANDING_A_CHIPDB_CHANGE.md): review the semantic
delta and repeat the required evidence before changing the checkpoint. Do not
repin it merely to unblock a build or test.

To replay the independently-set W1C derivative, select its exact profile in
`agamemnon.toml`:

```toml
[fabric]
qualified_profile = "l48-public32-gpio5-w1c-exact-map-2026-08-15"
```

It keeps the same four words but removes the write-bit1 set hook and uses MCU
GPIO5 DATA0/OUT_EN0 as a sustained-level set source. Low permits hold/clear;
high sets or reasserts with set priority; reset dominates. This is a
software-controlled qualification source, not a package-pin input,
asynchronous interrupt, or generic application event. In the generated
`mcu-fpga` project, also set `mcu.sources = ["src/main_gpio5_w1c.c"]`; the
default `src/main.c` is intentionally paired with the default bit1-hook image.

For the autonomous synchronous example, select
`l48-public32-autoevent-w1c-exact-map-2026-08-16` and set
`mcu.sources = ["src/main_autoevent_w1c.c"]`. It emits one reset-rearmed
count-seven fabric event into W1C status. This is an exact retained profile,
not a generic user-net socket or asynchronous/CDC contract.

### External AHB constant slave

The silicon-qualified `0x4147414d` behavior is the **pinned** routed netlist
(`qualification/mcu_ahb_constant_slave_routed.json`, the retained 2026-08-02
route), not a from-scratch synth+route today:

```bash
python -m agamemnon.cli pack qualification/mcu_ahb_constant_slave_routed.json constant_slave.bin
```

**A truly fresh build of this design is not currently guaranteed correct** —
see the 2026-08-18 T26 entry in
[CONDUCTION_REFRAME_STATUS.md](CONDUCTION_REFRAME_STATUS.md). nextpnr's route
choice for this design differs from the pinned 2026-08-02 build purely from chipdb/table
growth (the build's own `cap=2 seed=4` is unchanged), landing in a still-open
RMUX→IMUX→RMUX encoding defect at tile `X14Y8`. The direct-synthesis recipe
below still works and is useful for experimentation, but do not cite
`0x4147414d` for its output without independently re-verifying the resulting
bitstream — only the pinned artifact above is currently qualified:

```bash
agamemnon build examples/designs/mcu_ahb_constant_slave.v --uarch \
  --write-routed constant_slave.json -o constant_slave.bin
```

The pinned artifact returns `0x4147414d` for reads and completes writes
without changing that value. It qualifies the simultaneous `HRDATA[31:0]`,
`HREADYOUT`, and `HRESP` response bundle. It does not itself qualify the
sequential register bank, bus clock, wait states, errors, or byte access.
Separate L48 evidence qualifies
default-topology bus-clock delivery at one bus clock per MTIME tick, four exact direct-D sites, a
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
`PIN_n` always names decimal physical package lead `n`: `PIN_10` is LQFP lead
10, never hexadecimal `0x10`. Tile `(x,y,z)`, IOMUX, and RMUX numbers are
separate internal identifiers. The board's numbered pin labels use these same
decimal package-lead numbers.
Project builds select the device through `[project].device` (normally supplied
by the board definition); a one-off build with no project defaults to L48.
Retained exact L48 input demonstrations exist for PIN_10, PIN_11, PIN_12,
PIN_15, and PIN_19, plus exact single-consumer direct-combinational corridors
for PIN_25 through PIN_28. These are route-specific claims: the later
independent PIN_10 and PIN_12 held-input compositions both returned only low
despite correct routed logic (`VP-AGM-008`). Do not infer that a fresh generic
input route works from a prior exact demonstration. This does not qualify
general fanout or the complete four-link bidirectional node. Qualified L48
outputs are the left-edge PIN_25, PIN_26, PIN_27, and PIN_28, plus all ten
top-edge decimal physical leads PIN_10 through PIN_19,
and the qualified compositions are pinned in
`agamemnon/chipdb/pad_output_qualified_L48.csv`. Both the left-edge and the
top-edge pad images were originally built by the ordinary CLI with `--pcf` on
the Python-architecture (non-`--uarch`) path and under `--research-unsafe`,
because that placer composes experimental options. As of 2026-08-17,
`agamemnon build <source> --uarch --pcf <pcf>` (no `--research-unsafe`) also
builds release-strict images -- zero unmapped, predicted, or legacy selectors
-- for the left-edge four and nine of the ten top-edge leads (all but PIN_15,
which still fails to route under `--uarch`; it still needs the
Python-architecture `--research-unsafe` path). `AGAMEMNON_VENDOR_OUT_SLICE` is
now admitted at release maturity for exactly the four presentations
`pad_output_qualified_L48.csv` requires, gated by a dedicated value-bounded
policy check so no other value is release-admitted; any pad composition
outside that CSV still fails closed under `--uarch` too. Every one of those
`--uarch --pcf` images FCB-configured the real L48 device to `0x000f0002`
over a native, non-destructive SRAM session (`io_evidence.jsonl` trial
`pad-uarch-pcf-release-strict-vehicle-config-accept-20260817`). The Pico
toggle/electrical re-witness of that vehicle's own images is closed
for all ten output images (`io_evidence.jsonl` trial
`pad-uarch-pcf-toggle-rewitness-20260817`): the left-edge four and nine of
the ten top-edge outputs each toggle under both Pico pulls on exactly their
intended pin, matching the pre-existing research-unsafe-vehicle electrical
claim pad-for-pad. The five qualified-input demonstration builds' toggle/electrical re-witness
is closed on this vehicle: all five track their driven input under the
corrected active-drive procedure, reproducibly across two independent sweeps
(`io_evidence.jsonl` trial `pad-uarch-input-rewitness-closed-silicon-20260817`).
The research-unsafe-vehicle input qualification is unaffected.
Other packages are marked architecture-recovered for inspection, but strict
image emission rejects them until package-specific qualification is
admitted.

Typed `MCU_SPI0_MISO_INPUT` and `MCU_SPI1_MISO_INPUT` are refused in the
production path. Both campaign duplex images returned `0xffffffff` while their
vendor ensembles and active external slave passed. An older immutable SPI0
receive image remains evidence for only that exact composition; it does not
authorize a fresh typed MISO route.

PIN_25 also has one exact combined-cell qualification: hard-zero data with its
recorded six-pip OE corridor supports constant release/drive-low, static
readback, and a local-self-toggle dynamic-OE witness. The ordinary PCF path also
qualifies stepped external PIN_10 control with simultaneous readback through
the exact RMUX15 entry under both pulls. Separately, a retained vendor-routed
quad oracle now silicon-qualifies active-high OE polarity and open-drain-style
release/drive-low through the four distinct exact PIN_25 through PIN_28 OE
corridors. This is not a generic bidirectional API: ordinary source ingress and
simultaneous readback for PIN_26 through PIN_28, high-rate readback, the
divergent RMUX20 branch, active drive-high, registered OE, other pins, and other
corridors remain open.

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
agamemnon build arithmetic.v --uarch -o arithmetic.bin
```

One eligible chain may receive one physical seed and up to 32 arithmetic
stages in the qualified 33-site corridor. When every selected chain is short,
the allocator can instead maximize complete chains within the qualified
nine-site same-tile footprint. Unallocated and wider-than-32 chains degrade
independently to ordinary LUT arithmetic; use
`--no-hard-carry` to select that path for every chain. A malformed or branched
dedicated-carry graph still fails closed.

`--compact-maxd N` is an experimental uarch placement constraint. It limits
regional candidate tiles to Manhattan distance `N` from the regional root and
is forwarded through WSL. It has no default and is not part of the retry
ladder: an initial 36-bit LFSR A/B reduced routed pips and tier-2 edges at
radius 4, while a preserved congestion design became substantially slower and
timed out. Treat it as a diagnostic until a wider corpus establishes a useful
selection rule.

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

Supported `(--freq,AGAMEMNON_HSE)` pairs are the seven byte-exact
vendor-oracle profiles `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, `(100,16)`,
`(60,8)`, and `(100,12)` MHz, plus 38 further HSE=8 `SYSCLK` rates qualified
on silicon (spanning 4–248 MHz). Every other pair fails
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

`--research-unsafe` is for reverse-engineering probes, not supported images.
It selects the non-release recovered-knowledge graph and selector fallbacks and
always writes `design.bin.policy.json`. The sidecar distinguishes conflict-free
observations, vendor-derived conflicted/context/majority rows, decoded
templates, and predictions. Unresolved selectors still fail, and any negative-evidence edge stays blocked
(the set is empty — all fourteen catalogued edges were
admitted after clean silicon proof).

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

Use `agamemnon pack --research-unsafe design_routed.json design.bin` only when
the routed JSON was produced against the matching research graph.

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

An invalid experimental External-AHB slave can hold `HREADY` low so the hart
cannot honor OpenOCD's normal halt request. Recover it without cycling power or
touching flash by asserting the Debug Module's non-debug reset directly:

```bash
python tools/recover_wedged_ag32.py \
  --openocd "$AGAMEMNON_OPENOCD" \
  --scripts "$AGAMEMNON_OOCD_SCRIPTS"
```

The tool then halts the recovered core, checks device ID `0x40200001`, and
issues a normal reset. It is for a reachable debug module with an unresponsive
hart; it cannot repair a disconnected probe or persistent flash contents.

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
