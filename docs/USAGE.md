# AGaMEMnon — Usage

The `agamemnon` CLI is the user-facing front end to the open AG32 / AGRV2K toolchain, and it
drives **both halves of the chip** — the FPGA fabric and the flash / RISC-V side — with no vendor
binary in any path.

Pure-software subcommands (`build`, `pack`, `unpack`, `decode`, `encode`, `edit-lut`) run anywhere
with Python 3.8+ (`build` additionally needs `yosys` + `nextpnr-generic` on PATH). The hardware
subcommands (`probe`, `sram`, `backup`, `flash`, `image`) shell out to **stock OpenOCD + the shipped
open config** (`agamemnon/openocd/agrv2k.cfg`) — **no vendor "Supra" install and no vendor `agrv`
flash driver**. You need a CMSIS-DAP probe (the AGM DAP-Link "USB Blaster" is one) and an OpenOCD
built with RISC-V-over-ADIv5-DAP support (`target create riscv -dap`; that support is open — see
`riscv-collab/riscv-openocd` — but is absent from some prebuilt OpenOCDs, e.g. oss-cad-suite).

Every codec/edit path here is validated byte-for-byte against the vendor `af.exe`, and the
programming path on a real AG32 dev board (`DEVICE_ID 0x40200001`).

## Install

```bash
pip install -e .
```

This installs the `agamemnon` console script (entry point `agamemnon.cli:main`). If your
Python `Scripts`/`bin` directory is not on `PATH`, the equivalent invocation is
`python -m agamemnon.cli ...` — every example below works either way.

## OpenOCD resolution (hardware subcommands)

The hardware subcommands locate OpenOCD entirely through the environment — there is no `--agm`
option and no vendor install to point at:

```
$AGAMEMNON_OPENOCD       OpenOCD binary (default: `openocd` on PATH).
                         Must be built with `riscv -dap` support.
$AGAMEMNON_OOCD_CFG      OpenOCD config (default: the shipped agamemnon/openocd/agrv2k.cfg).
$AGAMEMNON_OOCD_SCRIPTS  only if your OpenOCD can't `find target/swj-dp.tcl` on its own.
```

> The generic `cortex_m`/`mem_ap` OpenOCD path does **not** work on this part — the SWD AP is a
> RISC-V DMI bridge. Use an OpenOCD with `target create riscv -dap` (the shipped `agrv2k.cfg` sets
> this up); no vendor config is needed.

---

## Software subcommands (no hardware)

### `build` — Verilog → flashable `.bin` (the whole FPGA flow)

Runs the complete open flow — yosys synth → nextpnr-generic place&route → our bitgen — from the
self-contained package (`engine/` + `chipdb/` + `synth/`). `yosys` and `nextpnr-generic` are found
on `PATH` (or under `$AGAMEMNON_OSS/bin`).

```bash
agamemnon build design.v -o design.bin
```

Writes `design.bin` (99,944-byte uncompressed image, for SRAM inject) and `design.bin.comp`
(LZW-compressed, for flash) alongside it.

Build-flow environment variables:

```
$AGAMEMNON_DEVICE        target package (default: AGRV2KL48). One of AGRV2KL100 / AGRV2KL64 /
                         AGRV2KL48 / AGRV2KQ32. Selects the per-package legal-pin set; the front-end
                         pin-NUMBER legality gate (device.py) rejects a design that DECLARES a PIN_n
                         the chosen package does not bond. It does NOT currently prune the fabric
                         IOB/pad bels the router may use — precise per-package physical pad
                         restriction is a documented follow-up pending the PIN_n->pad bond map
                         (in af.exe, not yet extracted). So today this gate is legality + label only.
```

Advanced / debug knobs (leave unset for normal use):

```
$AGAMEMNON_NO_EXIT_WL      =1 disables the silicon-validated MCU-dout exit-feeder whitelist
                           (reproduces the older dead-feeder routing; for debugging only).
$AGAMEMNON_EDGE_BLACKLIST  list of "src@x,y->dst@x,y" pips proven non-conducting on silicon, to
                           force the router around them. Empty (unset) leaves the pip graph unchanged.
```

### `pack` / `unpack` — routed JSON ↔ `.bin`

`pack` is the icepack-equivalent: a routed nextpnr "generic" `--write` JSON → flashable `.bin`.
`unpack` is iceunpack: a `.bin` → the 99,936-byte raw fabric config image.

```bash
agamemnon pack design_routed.json design.bin
agamemnon unpack design.bin -o raw.img
```

### `decode` — `.bin` → raw config image

Decompresses a fabric `.bin` (8-byte header + variable-width LZW) to the fixed
**99,936-byte** whole-fabric raw config image.

```bash
agamemnon decode fabric.bin -o raw.img
```

Expected output:

```
decoded fabric.bin -> raw.img (99936 bytes raw)
```

### `encode` — raw image → `.bin`

LZW-encodes a 99,936-byte raw image back into a `.bin`, prepending the fixed header
`40 20 00 01 | 00 00 ff ff` (`DEVICE_ID 0x40200001` | `max_index 0x0000ffff`). The encoder
is byte-exact with `af.exe`, so `decode`→`encode` reproduces a vendor `.bin` exactly.

```bash
agamemnon encode raw.img -o fabric.bin
```

Expected output (length depends on the design's compressibility):

```
encoded raw.img -> fabric.bin (742 byte .bin)
```

**Round-trip check** (verified during doc authoring on a synthetic 99,936-byte image):

```bash
agamemnon encode raw.img    -o fabric.bin
agamemnon decode fabric.bin -o raw_rt.img
cmp raw.img raw_rt.img          # silent => byte-exact
```

### `edit-lut` — change one LUT's truth table in a bitstream

Decodes a `.bin`, rewrites the 16-bit truth table of the logic element at tile coordinate
`(x,y,z)`, and re-encodes. The SRAM stores the complement of the mask (validated byte-exact
vs `af.exe`). No vendor binary is in the edit path; this reprograms a node's *logic* without
re-routing.

```bash
agamemnon edit-lut fabric.bin --le 20,12,1 --init 0x96e9 -o edited.bin
```

Expected output (one LUT's 16 init bits land on 4 raw bytes, 4 bits per word-line):

```
edit-lut LE(20,12,1) INIT=0x96e9: 4 raw byte(s) changed -> edited.bin
```

`--le` is `x,y,z`; `--init` is a 16-bit truth table accepted in any Python int base
(`0x96e9`, `38633`, etc.).

---

## Hardware subcommands (board + OpenOCD with `riscv -dap`)

These shell out to OpenOCD (resolved as above), driving a CMSIS-DAP probe (the AGM DAP-Link).
They require a connected AG32 dev board over the probe. **No vendor "Supra" install and no vendor
`agrv` flash driver** — `flash`/`image` drive the flash controller at `0x40001000` directly via
generic `mww`/`load_image` (the sequence was reverse-engineered by differential capture of the
vendor driver and verified on silicon).

### `probe` — read DEVICE_ID over SWD (read-only)

```bash
agamemnon probe
```

Expected output on a connected AGRV2K (read from `0x03000100`; confirmed on silicon):

```
DEVICE_ID = 0x40200001  (AGRV2K OK)
```

If no board/transport is found it prints `no device found ...` with the OpenOCD log tail and
exits non-zero.

### `sram` — inject a fabric image + firmware and run it (volatile)

Loads an uncompressed fabric `.bin` into SRAM (`0x20002000`) and a RISC-V firmware `.bin`
(`0x20000000`), runs it, and reads back result words from `0x20001000`. Nothing is written to
flash — this needs only generic RISC-V debug. The firmware is expected to FCB-config the fabric
from `0x20002000` (see `mcu/ag32.h` `ag32_fcb_config`) and write results to `0x20001000`.

```bash
agamemnon sram fw.bin -b design.bin
```

Expected output (word[0] is the FCB status):

```
result @ 0x20001000:
  [0] 0x000f0002
  ...
  (word[0] = FCB STAT 0x000f0002 -> fabric configured OK)
```

Flags: `-b/--fabric` (uncompressed fabric `.bin`), `-w/--words` (result words to read,
default 10), `--sleep` (ms to run before halting, default 500).

### `backup` — dump the whole 256 KB flash (read-only)

Do this before any flash write.

```bash
agamemnon backup full_flash.bin
```

Expected output:

```
backup -> full_flash.bin : OK (262144 B)
```

### `flash` — erase → program → verify (the open flasher)

Writes a binary to flash at `--addr`, erasing the sectors it spans, via the `0x40001000`
controller (no vendor `agrv` driver), then reads back and byte-verifies. With `--backup` it dumps
the full flash first so you always have a restore point. The fabric bitstream conventionally lives
at `0x80008100` (factory layout) or a 4 KB-aligned address of your choosing; MCU code is at
`0x80000000`.

```bash
agamemnon flash design.bin --addr 0x80008100 --backup full_flash.bin
```

Expected output:

```
backup -> full_flash.bin (262144 B)
flashing 3248 B at 0x80008100 (erasing 1 sector(s))
flash OK -- 3248 B byte-exact @ 0x80008100 (open flasher, no agrv driver)
```

Flags:

- `--addr <addr>` — flash address (required), e.g. `0x80008100`.
- `--backup <file>` — dump the full 256 KB flash before writing (strongly recommended).

On a verify mismatch it prints `flash VERIFY FAILED` (and reminds you to restore your `--backup`)
and exits non-zero.

### `image` — assemble (+ optionally flash) a combined boot image

Assembles a flash-boot image — MCU firmware (`0x80000000`) + uncompressed fabric (`--logic-addr`,
default `0x80010000`) + the option config-pointer — that self-boots after a power-cycle: the boot
ROM loads the fabric and runs the MCU. Without `--flash` it only prints the plan.

```bash
agamemnon image -b design.bin -m fw.bin                    # print the plan only
agamemnon image -b design.bin -m fw.bin --flash --backup full_flash.bin
```

Flags:

- `-b/--fabric` — uncompressed fabric `.bin` (required).
- `-m/--mcu` — MCU firmware `.bin` (→ `0x80000000`).
- `--logic-addr` — fabric flash address, 4 KB-aligned (default `0x80010000`).
- `--flash` — actually write it (default: plan only).
- `--backup <file>` — dump the full flash before writing.
- `--write-options` — also write the option config-pointer. **UNVERIFIED** program sequence
  (see `docs/flashboot/flash_controller.md`); opt-in, and requires `--backup`. `BOOT0=1` recovers
  if it goes wrong.

The MCU + fabric writes are the silicon-proven open flasher; the option-pointer write is the one
unverified step and is gated behind `--write-options` + `--backup`.

---

## Validation status of the examples above

| Subcommand | Validated how |
|---|---|
| `build` / `pack` / `unpack` | byte-exact vs `af.exe` on the regression fixtures; routes & self-boots on silicon |
| `encode` / `decode` | byte-exact round-trip vs `af.exe`; round-trip re-confirmed here on a 99,936-byte image |
| `edit-lut` | byte-exact vs `af.exe` (open LUT editor); reports the exact bytes changed |
| `probe` | read `0x40200001` from real AG32 silicon over the AGM DAP-Link |
| `sram` | fabric injected + run on silicon; FCB reports `STAT=0x000f0002` (configured OK) |
| `backup` / `flash` | full backup → erase → program → byte-verify validated on a real board (open flasher, no `agrv` driver) |
| `image` | MCU+fabric write path is the silicon-proven flasher; the design self-boots from flash after a power-cycle |
