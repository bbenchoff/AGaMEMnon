# Programming the AG32 — the `agamemnon` flasher

Gets your two halves (RISC-V firmware + fabric bitstream) onto the chip and makes it **boot from
flash on its own**. No vendor "Supra" install, no Quartus. Three transports, all of which reach the
same chip:

| transport | needs | good for |
|---|---|---|
| **SWD** (OpenOCD) | a CMSIS-DAP probe (AGM DAP-Link) + OpenOCD w/ `riscv -dap` (see `openocd/agrv2k.cfg`) | bench dev, debug, backup/restore |
| **UART bootloader** | BOOT0=1, a serial port, 460800 8N1 | in-system / field update, no probe |
| **native USB DFU** | the board's USB-C (chip has USB FS+OTG) + `dfu_usb.bin` stub | driverless flashing, one cable |

## Two ways to get a bitstream running

1. **SRAM-inject (volatile, for test):** halt the MCU, load the uncompressed fabric image to SRAM,
   and let a tiny stub stream it into the FCB (`ag32_fcb_config()` in `mcu/ag32.h`). Lost on reset,
   but needs *only* generic RISC-V debug — no flash driver. This is how bring-up was done.
2. **Flash-boot (persistent):** write the fabric bitstream (+ option bytes + MCU firmware) to flash;
   the boot ROM configures the fabric from flash at power-on and runs your firmware, **no debugger in
   the loop.** This is the real deployment path — proven on silicon (see below).

## The flash-boot recipe (proven on silicon)

The boot ROM, at power-on, reads the fabric config from flash, LZW-decompresses it, streams it into
the FCB, then branches on BOOT0 to your MCU code. The flash image the vendor `gen_batch` produces —
and that boot ROM expects — is:

```
0x81000000  option bytes     — where the fabric config lives + compressed/encrypted flags
0x80000000  MCU firmware     — your RISC-V .bin (reset code)
<logic_addr>                 — for a COMPRESSED config: [decompression algo blob][compressed .bin]
                               option bytes point PAST the algo (logic_addr + LOGIC_ALGO_SIZE)
```

**The layout, decoded** (from the boot ROM + `agrv2k.cfg`'s `check_logic`):
- Option-byte dwords at `0x81000030` (uncompressed config addr) / `0x81000038` (compressed) select
  the config source; compressed configs are prefixed by a **decompression-algorithm blob**
  (`LOGIC_ALGO_SIZE`, rounded up to 256 B) that the boot ROM runs to inflate the LZW image.
- The decompressed image carries a **CRC-32/BZIP2** the FCB checks; the first 4 bytes are the
  device-id header (big-endian `40 20 00 01`), matched against the live `DEVICE_ID`.

**Gotcha that cost an hour, so it's written down:** the decompression-algo blob can share a 4 KB
flash **sector** with the compressed config. A naive `flash write_image erase` of just the config
erases the whole sector and **wipes the algo's tail** → boot config silently fails. Rewrite the
*whole* affected sector range (algo + config) in one shot. And fabric config only happens at a real
**power-on reset** — an OpenOCD warm reset (nSRST) does **not** re-trigger it.

Proven end-to-end: an AGaMEMnon-built open bitstream (compressed) in flash → power-cycle → the fabric
came up and the MCU↔fabric loopback ran, no debugger attached.

## The CLI

The `agamemnon` CLI (run `agamemnon <cmd>`, or `python -m agamemnon.cli <cmd>`):

| command | status |
|---|---|
| `probe` — read DEVICE_ID over SWD | **works** (reads `0x40200001` via the shipped open cfg) |
| `sram <firmware> -b <fabric>` — inject a fabric bitstream + firmware, run, read `0x20001000` | **works, silicon-verified** — loaded an AGaMEMnon `mcu_loop2` bitstream + firmware, the fabric configured (`FCB STAT 0x000f0002`) and the 2-bit loopback inverted on all 4 combos, no vendor driver in the path |
| `backup <file>` — dump the whole 256 KB flash | works (read-only) |
| `flash <bin> --addr <a>` — erase + program a binary to flash, then byte-verify | **works, silicon-verified** — the **OPEN flasher**: drives the `0x40001000` controller directly via generic memory ops, **no vendor `agrv` driver**; erase→`0xFF`, program→byte-exact |
| `image -b <fabric> -m <mcu> --flash` — assemble + write a combined flash-boot image (MCU + fabric + option config-pointer) | **works** — the MCU + fabric writes reuse the silicon-proven open flasher; the option-pointer write is gated behind `--write-options` (still UNVERIFIED — see below) |

## The open flasher — done

The persistent-write path is now fully open. `flash` drives the `0x40001000` flash controller
(erase + program) itself, over generic OpenOCD memory ops through the shipped open cfg — **the vendor
`agrv` flash driver is no longer used anywhere.** The exact controller protocol (reverse-engineered
by differential-capturing the vendor driver, then verified on silicon) is in `flashboot/
flash_controller.md`. The only vendor-adjacent requirement left in the entire flow is an OpenOCD
*binary* built with `riscv -dap` (open, from `riscv-collab/riscv-openocd`).

## `image` — assembled boot image, and the one unverified step

`image` assembles a combined flash-boot image — MCU firmware (`0x80000000`) + the uncompressed fabric
(`--logic-addr`, default `0x80010000`) + the option-byte config pointer at `0x81000030` so the boot
ROM auto-loads the fabric at power-on. Without `--flash` it prints the plan; with `--flash` it writes
the MCU + fabric regions via the **silicon-proven open flasher**.

The **one** part still unverified is writing the option-byte config pointer itself (OPTKEYR + the
controller sequence). It is opt-in behind `--write-options`, requires `--backup`, and reads the
pointer back after writing; `BOOT0=1` recovers if it's wrong. Confirm that sequence by differential
capture (see `flashboot/flash_controller.md`) before trusting it. Until then, factory option bytes
already point at the factory logic address, so `flash <bin> --addr 0x80008100` writes a fabric that
self-boots with no option-byte change — the proven flash-boot recipe above.

- `openocd/agrv2k.cfg` — the open OpenOCD config (stock OpenOCD, no vendor build; needs `riscv -dap`).
- `flashboot/` — the proven flash-boot flow + image-layout notes.

