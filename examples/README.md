# AGaMEMnon examples

Runnable, copy-pasteable recipes for the open AG32 / AGRV2K bitstream toolchain. Every command goes
through the public CLI (`python -m agamemnon.cli ...`); nothing here calls a vendor binary.

Two of the three examples (`01`, `02`) are **offline** — they only touch `.bin` files on disk and need
no hardware. The third (`03`) talks to a real board over OpenOCD and is therefore a **documented recipe
you run by hand**, not a script that auto-executes.

## Prerequisites

- Python 3.x with the `agamemnon` package importable (run from the repo root, or `pip install -e .`).
- For the serial-mux hardware checker, `pip install -e ".[examples]"`
  installs PySerial in addition to AGaMEMnon.
- For `03` only: an AG32 dev board + a CMSIS-DAP probe (the AGM DAP-Link), and an OpenOCD built with
  `riscv -dap` support. It defaults to `openocd` on `PATH` + the shipped `agamemnon/openocd/agrv2k.cfg`;
  override the binary with `$AGAMEMNON_OPENOCD` if needed. No vendor "Supra" install and no vendor
  flash driver. `03` also requires the board to enumerate.

## A note on the input `.bin`

The offline examples default to a real vendor-built fabric bitstream that ships in this repo:

```
tests/fixtures/blinky.bin
```

That path is hard-coded for convenience. **Substitute your own `.bin`** by setting the `BIN`
variable at the top of each script (or `$Bin` in the `.ps1`). Any AGRV2K fabric `.bin` works — an
8-byte `DEVICE_ID 0x40200001 | max_index 0xffff` header followed by the variable-width LZW payload.

---

## 01 — round-trip a bitstream (offline)

`01_roundtrip.sh` / `01_roundtrip.ps1`

Decodes a `.bin` to its fixed **99,936-byte** raw fabric image, re-encodes that raw image back to a
`.bin`, and asserts the result is **byte-for-byte identical** to the input. This is the LZW codec's
self-consistency check — the same property validated against `af.exe` and on silicon.

```bash
./01_roundtrip.sh
# decoded ... (99936 bytes raw)
# encoded ... (2921 byte .bin)
# ROUND-TRIP BYTE-EXACT OK
```

If the input `.bin` carries trailing flash padding past the LZW stream, the re-encoded file can be
shorter than the original; that is expected and not a codec error. The supplied `blinky.bin` has no
such padding and matches exactly.

## 02 — edit a LUT INIT (offline)

`02_edit_lut.sh`

Takes a placed `.bin`, rewrites one logic element's 16-bit truth table with `edit-lut`, and shows
that **exactly one raw byte** changed between the original and the patched image — no re-route, no
vendor tool. The example flips LE `(20,12,1)` to INIT `0x96e9`; change `LE`/`INIT` at the top of the
script for a different cell. The toolchain stores the complement of the truth table in SRAM, matching
`af.exe` byte-exact.

```bash
./02_edit_lut.sh
# edit-lut LE(20,12,1) INIT=0x96e9: 1 raw byte(s) changed -> ...
# raw bytes differing: 1
#   byte 3185: 0xe8 -> 0xa8
```

## 03 — flash and verify on real hardware (recipe, NOT auto-run)

`03_flash_and_verify.sh`

> **This recipe writes the board's logic flash.** It is fully restorable (`flash --backup` dumps
> the whole 256 KB flash first), and it does **not** touch the MCU code at `0x80000000` when writing
> the logic region. The script is **commented out by default** — read it, then run the steps yourself.

Walks the hardware-validated path: `probe` the DEVICE_ID, then `flash` a `.bin` at `--addr 0x80008100`
with `--backup` — which takes a **full 256 KB flash backup**, erases the spanned sector(s), programs,
and verifies byte-exact. To undo, re-flash the whole chip from that backup
(`flash full_flash_backup.bin --addr 0x80000000`). See the inline comments for exactly what each
step writes and how to recover.

## serv_blinky — hardware-qualified CPU progress blink

`serv_blinky/` runs SERV from an aliased `addi`/`sw` program with an inferred
true dual-port BRAM register file. A registered program-address bit drives the
L48 onboard LED at PIN_25, so the observed blink is direct evidence of
continuing CPU fetch progress. Reset/run/reset and sustained BRAM A/B use pass
on hardware. This is a focused workload, not a general RISC-V compliance
result. The PIN_25 claim is specific to the L48 package and qualification
board.

## serial_mux — buffered serial multiplexer (build and hardware qualified)

`serial_mux/` implements three independent 9,600-baud 8N1 receivers, one-byte
elastic buffering per lane, and registered round-robin arbitration onto one
115,200-baud transmitter. Simultaneous A/B/C frames on L48 PIN_10/11/15
produce `ABCABC...` on PIN_16. The strict build uses 2,281 data PIPs including
17 dedicated-carry links, closes 25 MHz at 32.22 MHz, and emits no predicted,
legacy, or unmapped selectors. Pico qualification passed 4,096/4,096 exact
transactions. See `serial_mux/README.md`.
