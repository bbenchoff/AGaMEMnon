# Programming the AG32

AGaMEMnon communicates with the AG32 through CMSIS-DAP and OpenOCD. It drives
the on-chip flash controller directly and does not use the vendor `agrv`
OpenOCD flash driver.

Hardware commands require an OpenOCD executable implementing AGM's
RISC-V-over-ADIv5-DAP target option, `target create riscv -dap`. Stock upstream,
xPack, and OSS CAD Suite binaries do not contain that extension.

```bash
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd
```

`AGAMEMNON_OOCD_CFG` and `AGAMEMNON_OOCD_SCRIPTS` override the packaged target
configuration and OpenOCD script directory.

## Commands

| Command | Behavior |
|---|---|
| `agamemnon probe` | reads `DEVICE_ID`; no persistent write |
| `agamemnon sram FW --fabric FABRIC` | loads fabric and firmware into SRAM and runs them |
| `agamemnon backup FILE` | reads the complete 256-KiB main flash |
| `agamemnon flash FILE --addr ADDR` | erases touched sectors, programs, reads back, and verifies |
| `agamemnon image ...` | plans or writes MCU and uncompressed fabric regions |
| `agamemnon image ... --write-options` | opt-in, unsupported option-byte pointer operation |

UART bootloader and native USB DFU transports are not implemented.

## Volatile SRAM execution

```bash
agamemnon sram firmware.bin --fabric design.bin --words 10
```

The command places:

```text
0x20000000  firmware
0x20001000  result words
0x20002000  99,944-byte uncompressed fabric image
```

The firmware calls `ag32_fcb_config()`, performs the test or application work,
and stores optional observations at `0x20001000`. SRAM execution does not touch
flash and is the preferred development and qualification path.

## Main-flash programming

Create a complete backup before every write:

```bash
agamemnon backup full-flash.bin
agamemnon flash payload.bin --addr 0x80020000 --backup full-flash.bin
```

Main flash occupies `0x80000000..0x8003ffff`. `flash` erases every 4-KiB sector
spanned by the payload, programs through the controller at `0x40001000`, reads
the region back, and compares it byte-for-byte. A mismatch exits nonzero.

Option bytes occupy a separate region at `0x81000000` and are not modified by
`flash`.

## Existing compressed boot layout

On the qualified board, option bytes select a compressed fabric image at
`0x80008100` and a decompressor at `0x80007000`. Replace the image without
changing the option pointers:

```bash
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

The decompressor and fabric image can share a 4-KiB erase sector. Preserve and
restore the complete affected sector; erasing only the visible image fragment
can destroy part of the decompressor.

Fabric configuration from flash occurs on power-on. A debugger warm reset does
not rerun the complete fabric boot sequence.

## Image planning

```bash
agamemnon image --fabric design.bin --mcu firmware.bin
agamemnon image --fabric design.bin --mcu firmware.bin \
  --flash --backup full-flash.bin
```

Without `--flash`, `image` prints a write plan. With `--flash`, it writes the
MCU and uncompressed fabric regions through the same verified main-flash path.
Those writes do not change the boot ROM's fabric pointer.

`--write-options` also attempts to write the uncompressed-config pointer at
`0x81000030`. This operation is not a supported deployment path. It requires
an explicit flag and backup and must not be used to claim a bootable layout.

## Recovery

- Keep the complete 256-KiB backup off-board.
- Restore it with
  `agamemnon flash full-flash.bin --addr 0x80000000`.
- The SWD debug path is independent of main-flash contents.
- BOOT0=1 selects the mask-ROM serial recovery path, but AGaMEMnon does not
  implement that UART protocol.

See [flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md) for the memory map
and [flashboot/flash_controller.md](flashboot/flash_controller.md) for the
controller register sequence.
