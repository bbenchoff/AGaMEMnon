# Programming the AG32

AGaMEMnon can inspect and program the AG32 through a CMSIS-DAP probe. It drives
the on-chip flash controller directly and does not use the vendor `agrv`
OpenOCD flash driver.

The current transport boundary is important: hardware commands require an
OpenOCD executable that implements AGM's unpublished RISC-V-over-ADIv5-DAP
target option, `target create riscv -dap`. The shipped
`agamemnon/openocd/agrv2k.cfg` is open, but stock upstream, xPack, and
oss-cad-suite OpenOCD binaries do not contain that target extension.

Set the compatible executable explicitly when it is not on `PATH`:

```bash
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd
```

Optional overrides are `AGAMEMNON_OOCD_CFG` and
`AGAMEMNON_OOCD_SCRIPTS`.

## Available operations

| Command | State |
|---|---|
| `agamemnon probe` | Read-only and silicon-qualified; reads `DEVICE_ID = 0x40200001` |
| `agamemnon sram FW -b FABRIC` | Silicon-qualified volatile fabric/firmware load and execution |
| `agamemnon backup FILE` | Reads the complete 256-KiB main flash |
| `agamemnon flash FILE --addr ADDR` | Silicon-qualified main-flash sector erase, program, readback, and byte verification |
| `agamemnon image ...` | Plans or writes MCU and uncompressed fabric regions through the qualified flasher |
| `agamemnon image ... --write-options` | Implemented but explicitly unverified option-byte pointer write; opt-in and requires a backup |

UART bootloader and native USB DFU transports are not implemented by
AGaMEMnon.

## Volatile SRAM execution

`sram` loads an uncompressed 99,944-byte fabric image at `0x20002000`, loads a
freestanding RISC-V firmware binary at `0x20000000`, resumes the core, then
reads result words at `0x20001000`:

```bash
agamemnon sram firmware.bin --fabric design.bin --words 10
```

The firmware is responsible for calling `ag32_fcb_config()` and writing any
results. SRAM execution does not touch flash and is the preferred qualification
path.

## Main-flash programming

Back up before every write:

```bash
agamemnon backup full-flash.bin
agamemnon flash payload.bin --addr 0x80020000 --backup full-flash.bin
```

`flash` configures the controller at `0x40001000`, erases every 4-KiB sector
spanned by the payload, programs the bytes, reads the region back, and compares
it byte-for-byte. A mismatch exits nonzero.

Main flash occupies `0x80000000..0x8003ffff`. Option bytes are a separate
region at `0x81000000` and are not modified by `flash`.

## Existing compressed flash-boot layout

On the qualified board, factory option bytes select a compressed fabric image
at `0x80008100` and a decompressor blob at `0x80007000`. An AGaMEMnon
compressed output can replace the image at the existing config address:

```bash
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

The decompressor and config may share a 4-KiB erase sector. Erasing a config
fragment without restoring the full affected sector can destroy the tail of
the decompressor. Inspect the board's layout and preserve the complete shared
sector.

Fabric configuration from flash occurs at power-on. A debugger warm reset does
not rerun the complete fabric boot path.

## `image`

`image` accepts an uncompressed fabric image, optional MCU firmware, and a
4-KiB-aligned fabric address:

```bash
agamemnon image --fabric design.bin --mcu firmware.bin
agamemnon image --fabric design.bin --mcu firmware.bin \
  --flash --backup full-flash.bin
```

Without `--flash`, the command prints the write plan. With `--flash`, it writes
the MCU and fabric main-flash regions through the qualified open flasher.
Those writes alone do not change the boot ROM's fabric pointer.

`--write-options` additionally attempts to write the uncompressed-config
pointer at `0x81000030`. That option-byte sequence is not silicon-qualified.
The CLI therefore requires an explicit `--write-options` flag and a backup.
Do not treat an `image` main-flash write as a new bootable layout unless the
board's existing option pointer already selects that region or the pointer has
been set by a separately qualified method.

## Recovery

- Keep the complete 256-KiB backup outside the board.
- Restore it over SWD with `agamemnon flash full-flash.bin --addr 0x80000000`.
- BOOT0=1 selects the mask-ROM serial recovery path, but AGaMEMnon does not
  currently implement that UART protocol.
- The SWD debug path is independent of the contents of main flash.

The flash map is documented in
[flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md), and the confirmed
controller sequence is documented in
[flashboot/flash_controller.md](flashboot/flash_controller.md).
